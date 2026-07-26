"""CompassProject -> Ariane survey dict (plain python; no survey-library imports).

Shots are emitted in CONNECTIVITY order, not file order: Ariane chains shots by
FromID, so a shot can only be emitted once its from-station exists. Compass
projects routinely reference stations defined in later surveys or later .dat
files; a file-order walk creates spurious unanchored START shots which Ariane
renders at (0,0). Each shot still lands in its own survey's Section.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from speleoconvert.compass.backsights import (
    DISCREPANCY_DEG,
    BacksightConvention,
    azimuth_discrepancy,
    detect_backsight_convention,
    effective_measurements,
)
from speleoconvert.compass.model import CompassProject, CompassShot, CompassSurvey
from speleoconvert.geodesy import FT_TO_M, fixed_station_to_wgs84, utm_to_wgs84
from speleoconvert.report import (
    COMMENT,
    NATIVE,
    REPORT_ONLY,
    ConversionReport,
    StrictModeError,
)


def _iso_date(raw: str) -> str | None:
    parts = raw.split()
    if len(parts) == 3:
        try:
            m, d, y = (int(p) for p in parts)
            if y < 100:  # two-digit years occur in old Compass files
                y += 2000 if y <= 30 else 1900
            if y >= 1900:
                return date(y, m, d).isoformat()
        except ValueError:
            pass
    return None


def _append_comment(existing: str, addition: str) -> str:
    return f"{existing} | {addition}" if existing else addition


def _round_half_ft(x: float) -> float:
    """Depths to the nearest half foot: trig on whole-degree/foot survey data
    produces noise like 58.9994 that clutters Ariane's data table."""
    return round(x * 2.0) / 2.0


def map_project(
    project: CompassProject, *, strict: bool = False, report: ConversionReport
) -> dict:
    # fixed stations: name -> (lat, lon, z_ft); datum/zone taken per-link
    fixed: dict[str, tuple[float, float, float]] = {}
    for link in project.links:
        for fs in link.fixed_stations:
            if link.datum is not None and link.utm_zone is not None:
                lat, lon, z_m = fixed_station_to_wgs84(fs, link.utm_zone, link.datum)
                fixed[fs.name] = (lat, lon, z_m / FT_TO_M)
            else:
                report.add("fixed-station-no-datum", COMMENT, project.mak_path,
                           f"fixed station {fs.raw!r} has no datum/zone; "
                           "cannot geo-reference")
        for name in link.link_stations:
            report.add("mak-link-station", REPORT_ONLY, project.mak_path,
                       f"link station {name!r} (no coordinates in .mak)")
        for param in link.raw_params:
            report.add("mak-unknown-param", REPORT_ONLY, project.mak_path, param)
    if project.flags_raw:
        report.add("mak-display-flags", REPORT_ONLY, project.mak_path,
                   f"!{project.flags_raw};")
    for c in project.comments:
        report.add("mak-comment", REPORT_ONLY, project.mak_path, c)
    if project.convergence_deg is not None:
        report.add("mak-convergence", REPORT_ONLY, project.mak_path,
                   f"convergence={project.convergence_deg}")

    # base location -> WGS84, used to anchor components without a fixed station
    base_latlon: tuple[float, float] | None = None
    if (
        project.base_zone
        and project.datum is not None
        and project.base_easting_m is not None
        and project.base_northing_m is not None
        and not (project.base_easting_m == 0.0 and project.base_northing_m == 0.0)
    ):
        try:
            base_latlon = utm_to_wgs84(
                project.base_easting_m, project.base_northing_m,
                project.base_zone, project.datum,
            )
        except Exception as exc:  # unsupported datum/zone: anchor unavailable
            base_latlon = None
            report.add("mak-base-unconvertible", REPORT_ONLY, project.mak_path,
                       f"base location could not be geo-referenced: {exc}")

    z_ref = next(iter(fixed.values()))[2] if fixed else 0.0

    # Phase 1: build sections; collect every shot with its section index
    sections: list[dict] = []
    conventions: list[BacksightConvention] = []
    pending: list[tuple[int, CompassShot]] = []
    for dat in project.dat_files:
        for survey in dat.surveys:
            sections.append(_build_section(survey, report))
            conventions.append(detect_backsight_convention(survey))
            for shot in survey.shots:
                pending.append((len(sections) - 1, shot))

    # Phase 2: dependency-ordered emission
    emitter = _Emitter(sections, conventions, fixed, z_ref, base_latlon, report)
    remaining = pending
    while remaining:
        progressed = False
        deferred: list[tuple[int, CompassShot]] = []
        for sec_idx, shot in remaining:
            if emitter.known(shot.from_station):
                emitter.emit(sec_idx, shot)
                progressed = True
            else:
                deferred.append((sec_idx, shot))
        if not progressed and deferred:
            # nothing has a known from-station; prefer reversing a shot whose
            # TO station is known (side passage surveyed toward its tie-in)
            reversed_one = False
            for i, (sec_idx, shot) in enumerate(deferred):
                if emitter.known(shot.to_station):
                    emitter.emit_reversed(sec_idx, shot)
                    deferred.pop(i)
                    reversed_one = True
                    break
            if not reversed_one:
                # genuinely isolated component: seed its first station
                sec_idx, shot = deferred[0]
                emitter.seed(sec_idx, shot.from_station)
        remaining = deferred

    for name in fixed:
        if name not in emitter.seen_stations:
            report.add("fixed-station-orphan", REPORT_ONLY, project.mak_path,
                       f"fixed station {name!r} not present in any shot")

    if strict and (violations := report.strict_violations()):
        raise StrictModeError(violations)

    for section in sections:
        # survey-level notes are real data; TML's only clean per-record text
        # field is the shot comment, so they ride on the section's first shot
        if section["_survey_notes"] and section["shots"]:
            first = section["shots"][0]
            existing = first.get("comment") or ""
            first["comment"] = (
                f"{section['_survey_notes']} | {existing}" if existing
                else section["_survey_notes"]
            )
        elif section["_survey_notes"]:
            report.add("survey-notes-unattached", REPORT_ONLY,
                       section["_source_file"],
                       f"survey {section['name']!r} has no shots; notes kept in "
                       f"report only: {section['_survey_notes']}")
        del section["_source_file"]
        del section["_survey_notes"]

    return {
        "name": Path(project.mak_path).stem,
        "unit": "FT",
        "use_magnetic_azimuth": True,
        "first_start_absolute_elevation": z_ref,
        "sections": sections,
    }


def _build_section(survey: CompassSurvey, report: ConversionReport) -> dict:
    """Ariane's data table shows Section and Explorer as PLAIN text (embedded
    XML renders raw), so section fields stay clean: survey-level notes that are
    real data go onto the section's first shot comment; audit metadata
    (declination, format string, corrections) goes to the report only."""
    loc = survey.source_file
    notes: list[str] = []
    if survey.comment:
        report.add("survey-comment", COMMENT, loc,
                   "survey comment moved to first shot comment")
        notes.append(f"Survey comment: {survey.comment}")
    iso = _iso_date(survey.date_raw)
    if iso is None and survey.date_raw.strip():
        report.add("survey-date", COMMENT, loc,
                   f"unparseable SURVEY DATE {survey.date_raw!r}")
        notes.append(f"Compass survey date: {survey.date_raw}")
    if survey.discovery_raw:
        report.add("survey-discovery", COMMENT, loc,
                   f"DISCOVERY {survey.discovery_raw!r}")
        notes.append(f"Discovery: {survey.discovery_raw}")
    if survey.cave_name and survey.cave_name != survey.name:
        report.add("survey-cave-name", REPORT_ONLY, loc,
                   f"cave name {survey.cave_name!r}")
    if survey.format.lrud_association == "F":
        report.add("format-display-order", REPORT_ONLY, loc,
                   "LRUD recorded at FROM station (Ariane displays at shot end)")
    report.add("survey-format", REPORT_ONLY, loc,
               f"Compass FORMAT {survey.format.raw} (display metadata; "
               "not stored in TML)")
    for line_no in survey.placeholder_lines:
        report.add("placeholder-shot", REPORT_ONLY, f"{loc}:{line_no}",
                   "Compass editor placeholder row skipped (all-zero template)")

    # TML has no fields for declination or corrections; Ariane derives
    # declination from section date + survey location.
    if survey.declination_deg != 0.0:
        report.add("survey-declination", REPORT_ONLY, loc,
                   f"declination {survey.declination_deg} not stored in TML; "
                   "Ariane derives declination from date+location")
    elif iso:
        report.add("declination-zero", REPORT_ONLY, loc,
                   "DECLINATION 0.00 with a real date: Compass applied no "
                   "correction but Ariane will auto-compute one; bearings will "
                   "render rotated vs Compass")
    if survey.corrections and any(survey.corrections):
        report.add("survey-corrections", REPORT_ONLY, loc,
                   f"nonzero instrument corrections {survey.corrections} have no "
                   "Ariane equivalent (report-only, never applied)")
    if survey.corrections2 and any(survey.corrections2):
        report.add("survey-corrections", REPORT_ONLY, loc,
                   f"nonzero backsight corrections {survey.corrections2} have no "
                   "Ariane equivalent (report-only, never applied)")

    return {
        "name": survey.name,
        "survey": None,
        "date": iso,
        "explorers": [],
        "surveyors": list(survey.team),
        "declination": survey.declination_deg,
        "compass_format": survey.format.raw,
        "correction": list(survey.corrections or (0.0, 0.0, 0.0)),
        "correction2": list(survey.corrections2 or (0.0, 0.0)),
        "comment": None,
        "shots": [],
        "_source_file": loc,
        "_survey_notes": " | ".join(notes),
    }


class _Emitter:
    """Assigns global shot IDs and appends shot dicts to their sections."""

    def __init__(
        self,
        sections: list[dict],
        conventions: list[BacksightConvention],
        fixed: dict[str, tuple[float, float, float]],
        z_ref: float,
        base_latlon: tuple[float, float] | None,
        report: ConversionReport,
    ) -> None:
        self.sections = sections
        self.conventions = conventions
        self.fixed = fixed
        self.z_ref = z_ref
        self.base_latlon = base_latlon
        self.report = report
        self.station_shot_id: dict[str, int] = {}
        self.station_depth: dict[str, float] = {}
        self.seen_stations: set[str] = set()
        self.anchored_stations: set[str] = set()
        self.next_id = 0

    def known(self, station: str) -> bool:
        return station in self.station_shot_id or station in self.fixed

    def _start(self, sec_idx: int, station: str, *, anchored: bool) -> None:
        loc = self.sections[sec_idx]["_source_file"]
        start: dict = {
            "id_start": -1, "id_stop": self.next_id, "section": None,
            "shot_type": "START", "name": station,
            "length": 0.0, "azimuth": 0.0,
        }
        if station in self.fixed:
            lat, lon, z_ft = self.fixed[station]
            start["latitude"], start["longitude"] = lat, lon
            start["depth"] = round(self.z_ref - z_ft, 4)
            self.anchored_stations.add(station)
            self.report.add("fixed-station", NATIVE, loc,
                            f"{station} -> ({lat:.6f}, {lon:.6f})")
        else:
            start["depth"] = 0.0
            if not anchored:
                if self.base_latlon is not None:
                    start["latitude"], start["longitude"] = self.base_latlon
                    note = ("Disconnected survey component; placed at project "
                            "base location")
                else:
                    note = ("Disconnected survey component; no fixed station or "
                            "base location to anchor it")
                start["comment"] = note
                self.report.add("component-unfixed", REPORT_ONLY, loc,
                                f"component starting at {station!r}: {note}")
        self.station_shot_id[station] = self.next_id
        self.station_depth[station] = start["depth"]
        self.seen_stations.add(station)
        start["depth"] = _round_half_ft(start["depth"])
        self.sections[sec_idx]["shots"].append(start)
        self.next_id += 1

    def seed(self, sec_idx: int, station: str) -> None:
        self._start(sec_idx, station, anchored=False)

    def emit(self, sec_idx: int, shot: CompassShot) -> None:
        if shot.from_station not in self.station_shot_id:
            # known via fixed coordinates only: materialize its START shot
            self._start(sec_idx, shot.from_station, anchored=True)
        self._emit_between(sec_idx, shot, shot.from_station, shot.to_station,
                           reversed_=False)

    def emit_reversed(self, sec_idx: int, shot: CompassShot) -> None:
        if shot.to_station not in self.station_shot_id:
            self._start(sec_idx, shot.to_station, anchored=True)
        self._emit_between(sec_idx, shot, shot.to_station, shot.from_station,
                           reversed_=True)

    def _emit_between(
        self, sec_idx: int, shot: CompassShot, frm: str, to: str, *, reversed_: bool
    ) -> None:
        section = self.sections[sec_idx]
        loc = f"{section['_source_file']}:{shot.line_no}"
        self.seen_stations.add(frm)
        self.seen_stations.add(to)

        scomment = shot.comment
        conv = self.conventions[sec_idx]
        has_backsight = shot.azm2_deg is not None or shot.inc2_deg is not None
        merged_bearing, merged_inc = effective_measurements(shot, conv)

        if has_backsight:
            if shot.bearing_deg is not None and shot.azm2_deg is not None:
                disc = azimuth_discrepancy(
                    shot.bearing_deg, shot.azm2_deg,
                    corrected=conv.azimuth_corrected,
                )
                if disc > DISCREPANCY_DEG:
                    self.report.add(
                        "backsight-discrepancy", REPORT_ONLY, loc,
                        f"fore/back azimuths disagree by {disc:.1f} deg "
                        f"after convention correction",
                    )
            if shot.inclination_deg is not None and shot.inc2_deg is not None:
                inc_b = (shot.inc2_deg if conv.inclination_corrected
                         else -shot.inc2_deg)
                if abs(shot.inclination_deg - inc_b) > DISCREPANCY_DEG:
                    self.report.add(
                        "backsight-discrepancy", REPORT_ONLY, loc,
                        f"fore/back inclinations disagree by "
                        f"{abs(shot.inclination_deg - inc_b):.1f} deg after "
                        "convention correction",
                    )
            if shot.bearing_deg is None and shot.azm2_deg is not None:
                self.report.add("bearing-from-backsight", REPORT_ONLY, loc,
                                "no foresight azimuth; derived from backsight")
            sense = "corrected" if conv.azimuth_corrected else "reversed"
            bs = (f"Backsight azm2={shot.azm2_deg} inc2={shot.inc2_deg} "
                  f"averaged ({sense} convention)")
            self.report.add("backsight-averaged", REPORT_ONLY, loc, bs)
            scomment = _append_comment(scomment, bs)

        inc = merged_inc
        if inc is None:
            self.report.add("inclination-missing", REPORT_ONLY, loc,
                            "no inclination; depth propagated as level")
            inc = 0.0
        bearing = merged_bearing
        if bearing is None:
            self.report.add("bearing-missing", COMMENT, loc,
                            "missing bearing; wrote 0.0")
            scomment = _append_comment(scomment, "Compass: bearing missing")
            bearing = 0.0
        if reversed_:
            bearing = (bearing + 180.0) % 360.0
            inc = -inc
            self.report.add("shot-reversed", REPORT_ONLY, loc,
                            f"emitted reversed (recorded "
                            f"{shot.from_station} -> {shot.to_station})")

        depth_from = self.station_depth[frm]
        # full precision propagates through station_depth (rounding here would
        # random-walk down long chains); only the EMITTED values are rounded
        depth_to = depth_from - shot.length_ft * math.sin(math.radians(inc))

        f = shot.flags
        if f.exclude_length or f.exclude_plot or f.no_adjust:
            self.report.add("shot-flags", COMMENT, loc, f"flags #|{f.raw}#")
            scomment = _append_comment(scomment, f"Compass flags: #|{f.raw}#")
        for side, val in (("left", shot.left_ft), ("right", shot.right_ft),
                          ("up", shot.up_ft), ("down", shot.down_ft)):
            if val is None:
                self.report.add("lrud-missing", REPORT_ONLY, loc, f"{side} absent")

        entry: dict = {
            "id_start": self.station_shot_id[frm],
            "id_stop": self.next_id,
            "section": None,
            "name": to,
            "length": shot.length_ft,
            "azimuth": bearing,

            "depth": _round_half_ft(depth_to),
            "depth_start": _round_half_ft(depth_from),
            # LRUD is recorded facing the direction of travel; a reversed
            # shot faces the other way, so left and right swap (up/down don't)
            "left": shot.right_ft if reversed_ else shot.left_ft,
            "right": shot.left_ft if reversed_ else shot.right_ft,
            "up": shot.up_ft, "down": shot.down_ft,
            "excluded": f.exclude_all,
            "comment": scomment or None,
        }
        if merged_inc is not None:
            # explicit None fails the writer library's validation (the field
            # defaults to None only when the key is omitted entirely)
            entry["inclination"] = inc
        if to in self.station_shot_id:
            # Loop-closing shot. Ariane renders Type=CLOSURE shots dashed, as if
            # excluded; keep the shot REAL (solid, normal passage) and encode the
            # tie via closure_to_id + the duplicate station name.
            entry["shot_type"] = "REAL"
            entry["closure_to_id"] = self.station_shot_id[to]
            self.report.add("loop-closure", NATIVE, loc, f"loop closes onto {to}")
        else:
            entry["shot_type"] = "REAL"
            self.station_shot_id[to] = self.next_id
            self.station_depth[to] = depth_to
            if to in self.fixed and to not in self.anchored_stations:
                # A GPS anchor reached mid-traverse: Ariane's rooted-tree model
                # anchors one station per component, so preserve the secondary
                # coordinate on the shot that establishes the station.
                lat, lon, _z = self.fixed[to]
                self.anchored_stations.add(to)
                entry["comment"] = _append_comment(
                    entry["comment"] or "",
                    f"Compass fixed station {to}: WGS84 {lat:.6f}, {lon:.6f}",
                ) or None
                self.report.add("fixed-station-secondary", COMMENT, loc,
                                f"{to} -> ({lat:.6f}, {lon:.6f}) preserved in "
                                "shot comment (component already anchored)")
        section["shots"].append(entry)
        self.next_id += 1
