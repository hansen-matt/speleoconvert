"""Forward-compute station positions the Compass way; compare with .plt output."""
from __future__ import annotations

import math

from speleoconvert.compass.model import CompassProject


def compute_positions(project: CompassProject) -> dict[str, tuple[float, float, float]]:
    pos: dict[str, tuple[float, float, float]] = {}
    for dat in project.dat_files:
        for survey in dat.surveys:
            decl = survey.declination_deg
            for shot in survey.shots:
                if shot.from_station not in pos:
                    pos[shot.from_station] = (0.0, 0.0, 0.0)
                if shot.to_station in pos:
                    continue  # loop-closing shot: keep first-computed position
                n0, e0, v0 = pos[shot.from_station]
                inc = math.radians(shot.inclination_deg or 0.0)
                tb = math.radians((shot.bearing_deg or 0.0) + decl)
                horiz = shot.length_ft * math.cos(inc)
                pos[shot.to_station] = (
                    round(n0 + horiz * math.cos(tb), 6),
                    round(e0 + horiz * math.sin(tb), 6),
                    round(v0 + shot.length_ft * math.sin(inc), 6),
                )
    return pos


def compare(
    project: CompassProject, plt_stations: dict[str, tuple[float, float, float]]
) -> dict:
    ours = compute_positions(project)
    common = [s for s in ours if s in plt_stations]
    if not common:
        return {"n": 0, "max_err_ft": None, "p95_err_ft": None}
    ref = common[0]
    o0, p0 = ours[ref], plt_stations[ref]
    errs = []
    for s in common:
        o = [ours[s][i] - o0[i] for i in range(3)]
        p = [plt_stations[s][i] - p0[i] for i in range(3)]
        errs.append(math.dist(o, p))
    errs.sort()
    return {
        "n": len(common),
        "max_err_ft": round(errs[-1], 3),
        "p95_err_ft": round(errs[int(0.95 * (len(errs) - 1))], 3),
    }
