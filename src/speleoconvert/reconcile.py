"""Shot-by-shot reconciliation of a written .tml against its Compass source.

This is the data-integrity backstop: the survey data cost thousands of dive
hours, so every conversion is audited field-by-field. The TML is re-read here
with stdlib XML parsing (independent of the writer library), and every Compass
shot must be found with every measurement intact:

- station names, length (exact), azimuth/inclination (exact up to the
  documented backsight-averaging and chain-reversal transforms),
- LRUD including absent-vs-zero,
- depth deltas consistent with length x sin(inclination) up to half-foot
  display rounding,
- comments preserved verbatim (as a substring of the emitted comment),
- Compass X flags mapped to Excluded, backsight raw readings recorded,
- per-survey date and team names present on the section's shots,
- totals: shot count, summed length, and the full station-name set.

Returns a list of human-readable discrepancies; empty means fully reconciled.
"""
from __future__ import annotations

import math
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

from speleoconvert.compass.backsights import (
    detect_backsight_convention,
    effective_measurements,
)
from speleoconvert.compass.model import CompassProject, CompassShot

# emitted depths are rounded to the nearest 0.5 ft at BOTH ends of a shot
_DEPTH_TOL_FT = 1.01
_ANGLE_TOL = 1e-6


class _Expected:
    __slots__ = ("shot", "survey_name", "bearing", "inclination", "matched")

    def __init__(self, shot: CompassShot, survey_name: str,
                 bearing: float | None, inclination: float | None) -> None:
        self.shot = shot
        self.survey_name = survey_name
        self.bearing = bearing
        self.inclination = inclination
        self.matched = False


def _parse_tml(tml_path: str | Path) -> list[dict]:
    with zipfile.ZipFile(tml_path) as z:
        root = ElementTree.fromstring(z.read("Data.xml"))
    shots = []
    for el in root.findall("./Data/SurveyData"):
        def t(tag: str) -> str:
            return (el.findtext(tag) or "").strip()

        def f(tag: str) -> float | None:
            v = t(tag)
            return float(v) if v else None

        shots.append({
            "id": int(t("ID")), "from_id": int(t("FromID") or -1),
            "name": t("Name"), "section": t("Section"), "date": t("Date"),
            "type": t("Type"), "explorer": t("Explorer"),
            "comment": t("Comment"), "excluded": t("Excluded") == "true",
            "length": f("Length"), "azimuth": f("Azimut"),
            "inclination": f("Inclination"),
            "depth": f("Depth"), "depth_in": f("DepthIn"),
            "left": f("Left"), "right": f("Right"),
            "up": f("Up"), "down": f("Down"),
        })
    return shots


def _close(a: float | None, b: float | None, tol: float = _ANGLE_TOL) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def reconcile(project: CompassProject, tml_path: str | Path) -> list[str]:
    problems: list[str] = []
    tml_shots = _parse_tml(tml_path)
    name_of = {s["id"]: s["name"] for s in tml_shots}

    # ---- expected records from the Compass source -------------------------
    expected: dict[tuple[str, str, str], list[_Expected]] = defaultdict(list)
    surveys = []
    compass_stations: set[str] = set()
    n_compass = 0
    total_len_in = 0.0
    for dat in project.dat_files:
        for survey in dat.surveys:
            surveys.append(survey)
            conv = detect_backsight_convention(survey)
            for shot in survey.shots:
                bearing, inc = effective_measurements(shot, conv)
                expected[(survey.name, shot.from_station, shot.to_station)].append(
                    _Expected(shot, survey.name, bearing, inc)
                )
                compass_stations.add(shot.from_station)
                compass_stations.add(shot.to_station)
                n_compass += 1
                total_len_in += shot.length_ft

    # ---- match every TML shot back to a Compass shot ----------------------
    real = [s for s in tml_shots if s["type"] != "START"]
    total_len_out = 0.0
    for s in real:
        loc = f"{tml_path}: shot ID {s['id']} ({s['section']}/{s['name']})"
        frm = name_of.get(s["from_id"], "")
        direct = expected.get((s["section"], frm, s["name"]), [])
        rev = expected.get((s["section"], s["name"], frm), [])
        cands = [(e, False) for e in direct if not e.matched]
        cands += [(e, True) for e in rev if not e.matched]
        cands = [(e, r) for e, r in cands if _close(e.shot.length_ft, s["length"])]
        if not cands:
            problems.append(f"{loc}: no Compass shot matches "
                            f"({frm} -> {s['name']}, len {s['length']})")
            continue
        # prefer a candidate whose azimuth agrees. Comparison is circular:
        # raw Compass data contains out-of-range bearings (e.g. -91.0) that
        # normalize to the same direction (269.0) on write.
        def az_ok(e: _Expected, reversed_: bool) -> bool:
            exp = e.bearing if e.bearing is not None else 0.0
            if reversed_:
                exp = exp + 180.0
            got = s["azimuth"] if s["azimuth"] is not None else 0.0
            d = abs((exp - got) % 360.0)
            return min(d, 360.0 - d) <= 1e-4

        e, reversed_ = next(((e, r) for e, r in cands if az_ok(e, r)), cands[0])
        e.matched = True
        c = e.shot
        total_len_out += s["length"] or 0.0

        if not az_ok(e, reversed_):
            problems.append(f"{loc}: azimuth {s['azimuth']} does not match "
                            f"Compass {c.bearing_deg} (azm2={c.azm2_deg}, "
                            f"reversed={reversed_})")
        exp_inc = e.inclination
        if exp_inc is not None and reversed_:
            exp_inc = -exp_inc
        if not _close(exp_inc, s["inclination"], 1e-4):
            problems.append(f"{loc}: inclination {s['inclination']} != "
                            f"expected {exp_inc}")
        for side in ("left", "right", "up", "down"):
            want = getattr(c, f"{side}_ft")
            if not _close(want, s[side], 1e-6):
                problems.append(f"{loc}: {side} {s[side]} != Compass {want}")
        if s["depth"] is not None and s["depth_in"] is not None:
            inc_used = exp_inc if exp_inc is not None else 0.0
            dz_expected = -c.length_ft * math.sin(math.radians(inc_used))
            dz = s["depth"] - s["depth_in"]
            if abs(dz - dz_expected) > _DEPTH_TOL_FT:
                problems.append(f"{loc}: depth delta {dz:.2f} inconsistent with "
                                f"length*sin(inc) = {dz_expected:.2f}")
        if c.comment and c.comment not in s["comment"]:
            problems.append(f"{loc}: comment {c.comment!r} lost")
        if c.azm2_deg is not None and f"azm2={c.azm2_deg}" not in s["comment"]:
            problems.append(f"{loc}: backsight azm2={c.azm2_deg} not recorded")
        if c.flags.exclude_all != s["excluded"]:
            problems.append(f"{loc}: Excluded={s['excluded']} but Compass X flag "
                            f"is {c.flags.exclude_all}")
        if c.flags.raw and not c.flags.exclude_all and \
                f"#|{c.flags.raw}#" not in s["comment"]:
            problems.append(f"{loc}: flags #|{c.flags.raw}# not recorded")

    for records in expected.values():
        for e in records:
            if not e.matched:
                problems.append(
                    f"MISSING from TML: {e.survey_name}: "
                    f"{e.shot.from_station} -> {e.shot.to_station} "
                    f"len {e.shot.length_ft} (source line {e.shot.line_no})"
                )

    # ---- section-level metadata -------------------------------------------
    by_section: dict[str, list[dict]] = defaultdict(list)
    for s in tml_shots:
        by_section[s["section"]].append(s)
    for survey in surveys:
        sec_shots = by_section.get(survey.name, [])
        if not sec_shots:
            problems.append(f"section {survey.name!r} has no shots in TML")
            continue
        iso = _iso(survey.date_raw)
        if iso and iso not in {s["date"] for s in sec_shots}:
            problems.append(f"section {survey.name!r}: date {iso} lost")
        explorer_text = " ".join(s["explorer"] for s in sec_shots)
        for member in survey.team:
            if member not in explorer_text:
                problems.append(f"section {survey.name!r}: team member "
                                f"{member!r} lost")

    # ---- totals -------------------------------------------------------------
    if len(real) != n_compass:
        problems.append(f"shot count: {n_compass} in Compass, "
                        f"{len(real)} non-START in TML")
    if abs(total_len_in - total_len_out) > 1e-6 * max(1, n_compass):
        problems.append(f"total surveyed length changed: {total_len_in} ft in, "
                        f"{total_len_out} ft out")
    tml_names = {s["name"] for s in tml_shots}
    lost = compass_stations - tml_names
    if lost:
        problems.append(f"stations lost: {sorted(lost)[:10]}")

    return problems


def _iso(raw: str) -> str | None:
    from speleoconvert.mapping import _iso_date
    return _iso_date(raw)
