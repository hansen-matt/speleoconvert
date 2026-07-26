"""Validate a .tml against the de-facto Ariane format.

Ariane publishes no file spec. The reference set is:
- tests/fixtures/ariane_canonical.json — structural dump of an Ariane-generated
  file (vendored from the OpenSpeleo project's Python library repo, `ariane.json`);
- Ariane-authored sample files in that repo (hand_survey.tml, test_simple.tml,
  ...), from which the value formats below were derived (e.g. colors are
  `0xrrggbbaa`, booleans lowercase).

Stdlib only. Returns a list of human-readable issues; empty means conformant.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

# CaveFile children present in the canonical Ariane dump.
CANONICAL_TOP_LEVEL = {
    "CartoEllipse", "CartoLine", "CartoLinkedSurface", "CartoOverlay",
    "CartoPage", "CartoRectangle", "CartoSelection", "CartoSpline",
    "Constraints", "Data", "Layers", "ListAnnotation", "caveName",
    "firstStartAbsoluteElevation", "unit", "useMagneticAzimuth",
}
# Written additionally by the writer library; Ariane ignores unknown elements
# (verified by loading such files in Ariane).
TOLERATED_TOP_LEVEL = {"speleodb_id", "ListLidarRecords"}

# SurveyData children present in the canonical dump.
CANONICAL_SHOT_FIELDS = {
    "Azimut", "ClosureToID", "Color", "Comment", "Date", "Depth", "DepthIn",
    "Down", "Excluded", "Explorer", "FromID", "ID", "Inclination", "Latitude",
    "Left", "Length", "Locked", "Longitude", "Name", "Profiletype", "Right",
    "Section", "Shape", "Type", "Up",
}
TOLERATED_SHOT_FIELDS = {"UUID"}  # writer-library addition

_FLOAT = r"-?\d+(?:\.\d+)?(?:E-?\d+)?"
_FIELD_FORMATS: dict[str, str] = {
    "Color": r"0x[0-9a-fA-F]{8}",
    "Excluded": r"true|false",
    "Locked": r"true|false",
    "Type": r"REAL|START|VIRTUAL|CLOSURE",
    "Profiletype": r"VERTICAL|HORIZONTAL|PERPENDICULAR|BISECTION",
    "Date": r"\d{4}-\d{2}-\d{2}",
    "ID": r"\d+",
    "FromID": r"-1|\d+",
    "ClosureToID": r"-1|\d+",
    "Azimut": _FLOAT,
    "Length": _FLOAT,
    "Depth": _FLOAT,
    "DepthIn": _FLOAT,
    "Inclination": _FLOAT,
    "Latitude": _FLOAT,
    "Longitude": _FLOAT,
    "Left": _FLOAT,
    "Right": _FLOAT,
    "Up": _FLOAT,
    "Down": _FLOAT,
}
# fields where an empty element is meaningful ("absent")
_MAY_BE_EMPTY = {
    "Comment", "Name", "Explorer", "Section", "Shape", "Date", "Inclination",
    "Latitude", "Longitude", "Left", "Right", "Up", "Down", "DepthIn",
}


def validate_tml(path: str | Path) -> list[str]:
    issues: list[str] = []
    with zipfile.ZipFile(path) as z:
        if "Data.xml" not in z.namelist():
            return [f"{path}: no Data.xml in archive"]
        root = ElementTree.fromstring(z.read("Data.xml"))

    if root.tag != "CaveFile":
        issues.append(f"root element is {root.tag!r}, expected 'CaveFile'")

    for child in root:
        if child.tag not in CANONICAL_TOP_LEVEL | TOLERATED_TOP_LEVEL:
            issues.append(f"unknown top-level element <{child.tag}>")

    unit = root.findtext("unit", "")
    if unit not in ("ft", "m"):
        issues.append(f"unit is {unit!r}, expected 'ft' or 'm' (lowercase)")

    shots = root.findall("./Data/SurveyData")
    if not shots:
        issues.append("no Data/SurveyData shots")
    # IDs are resolved globally by Ariane (forward references in file order
    # are fine and occur naturally when sections interleave), so collect all
    # IDs first and only check set membership + uniqueness.
    all_ids: list[int] = []
    for shot in shots:
        try:
            all_ids.append(int(shot.findtext("ID", "-1")))
        except ValueError:
            pass
    id_set = set(all_ids)
    if len(all_ids) != len(id_set):
        issues.append("duplicate shot IDs present")
    for i, shot in enumerate(shots):
        loc = f"SurveyData[{i}]"
        for field in shot:
            if field.tag not in CANONICAL_SHOT_FIELDS | TOLERATED_SHOT_FIELDS:
                issues.append(f"{loc}: unknown field <{field.tag}>")
                continue
            text = (field.text or "").strip()
            fmt = _FIELD_FORMATS.get(field.tag)
            if not text:
                if fmt and field.tag not in _MAY_BE_EMPTY:
                    issues.append(f"{loc}: <{field.tag}> is empty")
                continue
            if fmt and not re.fullmatch(fmt, text):
                issues.append(f"{loc}: <{field.tag}>={text!r} does not match "
                              f"/{fmt}/")
        # referential integrity (global: Ariane resolves IDs over the file)
        try:
            from_id = int(shot.findtext("FromID", "-1"))
            closure = int(shot.findtext("ClosureToID", "-1"))
        except ValueError:
            continue  # already reported by format checks
        if from_id != -1 and from_id not in id_set:
            issues.append(f"{loc}: FromID {from_id} references no shot ID")
        if closure != -1 and closure not in id_set:
            issues.append(f"{loc}: ClosureToID {closure} references no shot ID")
        az = shot.findtext("Azimut", "")
        try:
            # 360.0 occurs in raw Compass data and is preserved verbatim
            if az and not 0.0 <= float(az) <= 360.0:
                issues.append(f"{loc}: Azimut {az} outside [0, 360]")
        except ValueError:
            pass
    return issues
