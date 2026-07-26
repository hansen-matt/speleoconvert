"""CompassProject -> Ariane survey dict (plain python; no survey-library imports)."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from speleoconvert.compass.model import CompassProject, CompassSurvey
from speleoconvert.geodesy import fixed_station_to_wgs84
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
            if y >= 1900:
                return date(y, m, d).isoformat()
        except ValueError:
            pass
    return None


def _append_comment(existing: str, addition: str) -> str:
    return f"{existing} | {addition}" if existing else addition


def map_project(
    project: CompassProject, *, strict: bool = False, report: ConversionReport
) -> dict:
    # fixed stations: name -> (lat, lon, z_m); datum/zone taken per-link
    fixed: dict[str, tuple[float, float, float]] = {}
    for link in project.links:
        for fs in link.fixed_stations:
            fixed[fs.name] = fixed_station_to_wgs84(fs, link.utm_zone, link.datum)
        for param in link.raw_params:
            report.add("mak-unknown-param", REPORT_ONLY, project.mak_path, param)
    if project.flags_raw:
        report.add("mak-display-flags", REPORT_ONLY, project.mak_path,
                   f"!{project.flags_raw};")
    for c in project.comments:
        report.add("mak-comment", REPORT_ONLY, project.mak_path, c)
    report.add("mak-convergence", REPORT_ONLY, project.mak_path,
               f"convergence={project.convergence_deg}")

    z_ref = next(iter(fixed.values()))[2] if fixed else 0.0

    station_shot_id: dict[str, int] = {}
    station_depth: dict[str, float] = {}
    seen_stations: set[str] = set()
    next_id = 0
    sections: list[dict] = []

    for dat in project.dat_files:
        for survey in dat.surveys:
            section, next_id = _map_survey(
                survey, fixed, z_ref, station_shot_id, station_depth,
                seen_stations, next_id, report,
            )
            sections.append(section)

    for name in fixed:
        if name not in seen_stations:
            report.add("fixed-station-orphan", COMMENT, project.mak_path,
                       f"fixed station {name!r} not present in any shot")
            if sections:
                sections[0]["comment"] = _append_comment(
                    sections[0]["comment"] or "",
                    f"Orphan fixed station from .mak: {name}",
                )

    if strict and (violations := report.strict_violations()):
        raise StrictModeError(violations)

    return {
        "name": Path(project.mak_path).stem,
        "unit": "FT",
        "use_magnetic_azimuth": True,
        "first_start_absolute_elevation": z_ref,
        "sections": sections,
    }


def _map_survey(
    survey: CompassSurvey,
    fixed: dict[str, tuple[float, float, float]],
    z_ref: float,
    station_shot_id: dict[str, int],
    station_depth: dict[str, float],
    seen_stations: set[str],
    next_id: int,
    report: ConversionReport,
) -> tuple[dict, int]:
    loc = survey.source_file
    comment = survey.comment
    iso = _iso_date(survey.date_raw)
    if iso is None and survey.date_raw.strip():
        report.add("survey-date", COMMENT, loc,
                   f"unparseable SURVEY DATE {survey.date_raw!r}")
        comment = _append_comment(comment, f"Compass survey date: {survey.date_raw}")
    if survey.discovery_raw:
        report.add("survey-discovery", COMMENT, loc,
                   f"DISCOVERY {survey.discovery_raw!r}")
        comment = _append_comment(comment, f"Discovery: {survey.discovery_raw}")
    if survey.cave_name and survey.cave_name != survey.name:
        report.add("survey-cave-name", COMMENT, loc, f"cave name {survey.cave_name!r}")
        comment = _append_comment(comment, f"Cave: {survey.cave_name}")
    if survey.format.lrud_association == "F":
        report.add("format-display-order", REPORT_ONLY, loc,
                   "LRUD recorded at FROM station (Ariane displays at shot end)")

    section: dict = {
        "name": survey.name,
        "survey": None,
        "date": iso,
        "explorers": [],
        "surveyors": list(survey.team),
        "declination": survey.declination_deg,
        "compass_format": survey.format.raw,
        "correction": list(survey.corrections or (0.0, 0.0, 0.0)),
        "correction2": list(survey.corrections2 or (0.0, 0.0)),
        "comment": comment or None,
        "shots": [],
    }
    shots: list[dict] = section["shots"]

    for shot in survey.shots:
        sloc = f"{loc}:{shot.line_no}"
        seen_stations.add(shot.from_station)
        seen_stations.add(shot.to_station)

        if shot.from_station not in station_shot_id:
            start: dict = {
                "id_start": -1, "id_stop": next_id, "section": None,
                "shot_type": "START", "name": shot.from_station,
                "length": 0.0, "azimuth": 0.0,
            }
            if shot.from_station in fixed:
                lat, lon, z_m = fixed[shot.from_station]
                start["latitude"], start["longitude"] = lat, lon
                start["depth"] = round(z_ref - z_m, 4)
                report.add("fixed-station", NATIVE, sloc,
                           f"{shot.from_station} -> ({lat:.6f}, {lon:.6f})")
            else:
                start["depth"] = 0.0
            station_shot_id[shot.from_station] = next_id
            station_depth[shot.from_station] = start["depth"]
            shots.append(start)
            next_id += 1

        depth_from = station_depth[shot.from_station]
        inc = shot.inclination_deg
        if inc is None:
            report.add("inclination-missing", REPORT_ONLY, sloc,
                       "no inclination; depth propagated as level")
            inc = 0.0
        depth_to = round(depth_from - shot.length_ft * math.sin(math.radians(inc)), 4)

        scomment = shot.comment
        bearing = shot.bearing_deg
        if bearing is None:
            report.add("bearing-missing", COMMENT, sloc, "missing bearing; wrote 0.0")
            scomment = _append_comment(scomment, "Compass: bearing missing")
            bearing = 0.0

        f = shot.flags
        if f.exclude_length or f.exclude_plot or f.no_adjust:
            report.add("shot-flags", COMMENT, sloc, f"flags #|{f.raw}#")
            scomment = _append_comment(scomment, f"Compass flags: #|{f.raw}#")
        if shot.azm2_deg is not None or shot.inc2_deg is not None:
            bs = f"Backsight: azm2={shot.azm2_deg} inc2={shot.inc2_deg}"
            report.add("backsight", COMMENT, sloc, bs)
            scomment = _append_comment(scomment, bs)
        for side, val in (("left", shot.left_ft), ("right", shot.right_ft),
                          ("up", shot.up_ft), ("down", shot.down_ft)):
            if val is None:
                report.add("lrud-missing", REPORT_ONLY, sloc, f"{side} absent")

        entry: dict = {
            "id_start": station_shot_id[shot.from_station],
            "id_stop": next_id,
            "section": None,
            "name": shot.to_station,
            "length": shot.length_ft,
            "azimuth": bearing,
            "inclination": shot.inclination_deg,
            "depth": depth_to,
            "depth_start": depth_from,
            "left": shot.left_ft, "right": shot.right_ft,
            "up": shot.up_ft, "down": shot.down_ft,
            "excluded": f.exclude_all,
            "comment": scomment or None,
        }
        if shot.to_station in station_shot_id:
            entry["shot_type"] = "CLOSURE"
            entry["closure_to_id"] = station_shot_id[shot.to_station]
            report.add("loop-closure", NATIVE, sloc,
                       f"loop closes onto {shot.to_station}")
        else:
            entry["shot_type"] = "REAL"
            station_shot_id[shot.to_station] = next_id
            station_depth[shot.to_station] = depth_to
        shots.append(entry)
        next_id += 1

    return section, next_id
