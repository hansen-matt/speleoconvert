"""Forward-compute station positions the Compass way; compare with .plt output.

Coordinates are (north_ft, east_ft, vert_ft) in the project's UTM-feet frame,
matching Compass .plt files. Fixed stations from the .mak anchor components at
their absolute coordinates; components with no fixed station get their own
origin and are compared relative to a per-component reference station.
"""
from __future__ import annotations

import math

from speleoconvert.compass.backsights import (
    detect_backsight_convention,
    effective_measurements,
)
from speleoconvert.compass.model import CompassProject
from speleoconvert.geodesy import FT_TO_M

Coord = tuple[float, float, float]


def _shot_delta(length_ft, bearing_deg, inclination_deg, declination_deg) -> Coord:
    inc = math.radians(inclination_deg or 0.0)
    tb = math.radians((bearing_deg or 0.0) + declination_deg)
    horiz = length_ft * math.cos(inc)
    return (
        horiz * math.cos(tb),
        horiz * math.sin(tb),
        length_ft * math.sin(inc),
    )


def solve_positions(
    project: CompassProject,
) -> tuple[dict[str, Coord], dict[str, int]]:
    """Return (positions, component id per station)."""
    pos: dict[str, Coord] = {}
    comp: dict[str, int] = {}

    # Component 0: all fixed stations share the absolute UTM-feet frame.
    for link in project.links:
        for fs in link.fixed_stations:
            scale = 1.0 if fs.unit == "f" else 1.0 / FT_TO_M
            pos[fs.name] = (fs.y * scale, fs.x * scale, fs.z * scale)
            comp[fs.name] = 0

    next_comp = 1
    remaining = []
    for dat in project.dat_files:
        for survey in dat.surveys:
            conv = detect_backsight_convention(survey)
            for shot in survey.shots:
                bearing, inc = effective_measurements(shot, conv)
                remaining.append((shot, survey.declination_deg, bearing, inc))
    while remaining:
        progressed = False
        deferred = []
        for item in remaining:
            shot, decl, bearing, inc = item
            f, t = shot.from_station, shot.to_station
            f_known, t_known = f in pos, t in pos
            if f_known and t_known:
                progressed = True  # loop-closing shot; keep first positions
                continue
            if not f_known and not t_known:
                deferred.append(item)
                continue
            dn, de, dv = _shot_delta(shot.length_ft, bearing, inc, decl)
            if f_known:
                n0, e0, v0 = pos[f]
                pos[t] = (round(n0 + dn, 6), round(e0 + de, 6), round(v0 + dv, 6))
                comp[t] = comp[f]
            else:
                n0, e0, v0 = pos[t]
                pos[f] = (round(n0 - dn, 6), round(e0 - de, 6), round(v0 - dv, 6))
                comp[f] = comp[t]
            progressed = True
        if not progressed and deferred:
            # isolated component: seed its first station at a fresh origin
            seed = deferred[0][0].from_station
            pos[seed] = (0.0, 0.0, 0.0)
            comp[seed] = next_comp
            next_comp += 1
        remaining = deferred
    return pos, comp


def compute_positions(project: CompassProject) -> dict[str, Coord]:
    return solve_positions(project)[0]


def compare(
    project: CompassProject, plt_stations: dict[str, Coord]
) -> dict:
    ours, comp = solve_positions(project)
    errs: list[float] = []
    by_comp: dict[int, list[str]] = {}
    for s in ours:
        if s in plt_stations:
            by_comp.setdefault(comp[s], []).append(s)
    for stations in by_comp.values():
        ref = stations[0]
        o0, p0 = ours[ref], plt_stations[ref]
        for s in stations:
            o = [ours[s][i] - o0[i] for i in range(3)]
            p = [plt_stations[s][i] - p0[i] for i in range(3)]
            errs.append(math.dist(o, p))
    if not errs:
        return {"n": 0, "max_err_ft": None, "p95_err_ft": None, "extent_ft": None}
    errs.sort()
    ns = [v[0] for v in plt_stations.values()]
    es = [v[1] for v in plt_stations.values()]
    extent = math.hypot(max(ns) - min(ns), max(es) - min(es))
    return {
        "n": len(errs),
        "max_err_ft": round(errs[-1], 3),
        "p95_err_ft": round(errs[int(0.95 * (len(errs) - 1))], 3),
        "extent_ft": round(extent, 1),
    }
