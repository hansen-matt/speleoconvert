"""Redundant-backsight handling: convention detection and fore/back averaging.

Compass averages redundant backsights into the working azimuth/inclination at
compile time. Whether backsights were recorded raw (pointing back down the
shot, ~180 deg from the foresight) or pre-corrected (same sense as the
foresight) is an entry convention, so it is detected empirically per survey
from the median fore/back angular difference. Stdlib only.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from speleoconvert.compass.model import CompassSurvey

# fore/back disagreement (after convention correction) above this is reported
DISCREPANCY_DEG = 5.0


@dataclass(frozen=True)
class BacksightConvention:
    azimuth_corrected: bool      # True: back az recorded in the foresight sense
    inclination_corrected: bool  # True: back inc recorded in the foresight sense


def _folded_diff(a: float, b: float) -> float:
    """Angular difference folded to [0, 180]."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def detect_backsight_convention(survey: CompassSurvey) -> BacksightConvention:
    az_folds = [
        _folded_diff(sh.azm2_deg, sh.bearing_deg)
        for sh in survey.shots
        if sh.azm2_deg is not None and sh.bearing_deg is not None
    ]
    # raw/uncorrected backsights sit near 180; corrected near 0
    az_corrected = bool(az_folds) and statistics.median(az_folds) < 90.0

    inc_votes = []
    for sh in survey.shots:
        if sh.inc2_deg is None or sh.inclination_deg is None:
            continue
        if abs(sh.inclination_deg) < 2.0 and abs(sh.inc2_deg) < 2.0:
            continue  # too flat to distinguish sign conventions
        inc_votes.append(abs(sh.inc2_deg - sh.inclination_deg)
                         < abs(sh.inc2_deg + sh.inclination_deg))
    inc_corrected = bool(inc_votes) and (sum(inc_votes) > len(inc_votes) / 2)

    return BacksightConvention(az_corrected, inc_corrected)


def average_azimuth(fore: float, back: float, *, corrected: bool) -> float:
    """Circular mean of foresight and (convention-corrected) backsight."""
    b = back if corrected else (back + 180.0) % 360.0
    x = math.cos(math.radians(fore)) + math.cos(math.radians(b))
    y = math.sin(math.radians(fore)) + math.sin(math.radians(b))
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return fore  # antipodal pair: no meaningful mean, keep the foresight
    return round(math.degrees(math.atan2(y, x)) % 360.0, 4)


def average_inclination(fore: float, back: float, *, corrected: bool) -> float:
    b = back if corrected else -back
    return round((fore + b) / 2.0, 4)


def azimuth_discrepancy(fore: float, back: float, *, corrected: bool) -> float:
    b = back if corrected else (back + 180.0) % 360.0
    return _folded_diff(fore, b)


def effective_measurements(shot, conv: BacksightConvention):
    """(bearing, inclination) after backsight averaging; None stays None only
    when neither a foresight nor a backsight reading exists."""
    bearing, inc = shot.bearing_deg, shot.inclination_deg
    if shot.azm2_deg is not None:
        if bearing is not None:
            bearing = average_azimuth(bearing, shot.azm2_deg,
                                      corrected=conv.azimuth_corrected)
        else:
            bearing = (shot.azm2_deg if conv.azimuth_corrected
                       else (shot.azm2_deg + 180.0) % 360.0)
    if shot.inc2_deg is not None:
        if inc is not None:
            inc = average_inclination(inc, shot.inc2_deg,
                                      corrected=conv.inclination_corrected)
        else:
            inc = shot.inc2_deg if conv.inclination_corrected else -shot.inc2_deg
    return bearing, inc
