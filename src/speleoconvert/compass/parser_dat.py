"""Parser for Compass .dat survey files. Stdlib only, lossless, hard errors."""
from __future__ import annotations

import re
from pathlib import Path

from speleoconvert.compass.model import (
    CompassDatFile,
    CompassShot,
    CompassSurvey,
    FormatSpec,
    ParseError,
    ShotFlags,
)

_DECL_RE = re.compile(
    r"DECLINATION:\s*(?P<decl>-?[\d.]+)\s+"
    r"FORMAT:\s*(?P<fmt>\S+)"
    r"(?:\s+CORRECTIONS:\s*(?P<c1>-?[\d.]+)\s+(?P<c2>-?[\d.]+)\s+(?P<c3>-?[\d.]+))?"
    r"(?:\s+CORRECTIONS2:\s*(?P<d1>-?[\d.]+)\s+(?P<d2>-?[\d.]+))?"
    r"(?:\s+DISCOVERY:\s*(?P<disc>.*?))?\s*$"
)
_HEADER_BASE = ["FROM", "TO", "LENGTH", "BEARING", "INC", "LEFT", "UP", "DOWN", "RIGHT"]
_LRUD_SENTINEL = -9.85       # values <= this are "absent" (-9.90, -999.25)
_BACKSIGHT_SENTINEL = -900.0


def parse_dat(path: str | Path) -> CompassDatFile:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("cp437")
    except UnicodeDecodeError as e:
        raise ParseError(str(path), 0, f"undecodable byte: {e}") from e
    return parse_dat_text(text, file=str(path))


def parse_dat_text(text: str, *, file: str) -> CompassDatFile:
    text = text.rstrip("\x1a\r\n \t")
    surveys: list[CompassSurvey] = []
    offset = 0  # running line offset for error locations
    for block in text.split("\x0c"):
        block_lines = block.splitlines()
        # skip leading blank lines (common after form feed)
        while block_lines and not block_lines[0].strip():
            block_lines.pop(0)
            offset += 1
        if block_lines:
            surveys.append(_parse_survey(block_lines, file=file, line_offset=offset))
        offset += len(block_lines)
    if not surveys:
        raise ParseError(file, 0, "no surveys found")
    return CompassDatFile(path=file, surveys=tuple(surveys))


def _get(lines: list[str], idx: int, file: str, off: int, what: str) -> str:
    if idx >= len(lines):
        raise ParseError(file, off + len(lines), f"unexpected end of survey: missing {what}")
    return lines[idx]


def _parse_survey(lines: list[str], *, file: str, line_offset: int) -> CompassSurvey:
    def ln(i: int) -> int:  # 1-based file line number
        return line_offset + i + 1

    # The cave-name line may be blank or absent; anchor on the SURVEY NAME line
    # instead of assuming a fixed position (seen in real files, e.g. Region_4.DAT).
    name_idx = next(
        (i for i, line in enumerate(lines[:4]) if "SURVEY NAME:" in line), None
    )
    if name_idx is None:
        raise ParseError(file, ln(0), f"no SURVEY NAME line near {lines[0]!r}")
    cave_name = lines[name_idx - 1].strip() if name_idx >= 1 else ""
    name = lines[name_idx].split("SURVEY NAME:", 1)[1].strip()
    base = name_idx  # header lines are positioned relative to SURVEY NAME

    date_line = _get(lines, base + 1, file, line_offset, "SURVEY DATE")
    if "SURVEY DATE:" not in date_line:
        raise ParseError(file, ln(base + 1), f"expected SURVEY DATE, got {date_line!r}")
    date_part = date_line.split("SURVEY DATE:", 1)[1]
    if "COMMENT:" in date_part:
        date_raw, comment = date_part.split("COMMENT:", 1)
    else:
        date_raw, comment = date_part, ""
    date_raw, comment = date_raw.strip(), comment.strip()

    team_hdr = _get(lines, base + 2, file, line_offset, "SURVEY TEAM")
    if "SURVEY TEAM:" not in team_hdr:
        raise ParseError(file, ln(base + 2), f"expected SURVEY TEAM, got {team_hdr!r}")
    team_line = _get(lines, base + 3, file, line_offset, "team names").strip()
    team: tuple[str, ...] = ()
    if team_line and team_line != "?":
        team = tuple(t.strip() for t in team_line.split(",") if t.strip())

    decl_line = _get(lines, base + 4, file, line_offset, "DECLINATION")
    m = _DECL_RE.search(decl_line)
    if not m:
        raise ParseError(file, ln(base + 4), f"cannot parse DECLINATION line: {decl_line!r}")
    fmt = FormatSpec.parse(m["fmt"], file=file, line_no=ln(base + 4))
    corrections = None
    if m["c1"] is not None:
        corrections = (float(m["c1"]), float(m["c2"]), float(m["c3"]))
    corrections2 = None
    if m["d1"] is not None:
        corrections2 = (float(m["d1"]), float(m["d2"]))

    # find column header row
    hdr_idx = None
    for i in range(base + 5, len(lines)):
        if "FROM" in lines[i] and "TO" in lines[i] and "LENGTH" in lines[i]:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ParseError(file, ln(base + 5), "missing shot column header row")
    cols = lines[hdr_idx].split()
    has_backsights = "AZM2" in cols
    expected = _HEADER_BASE + (["AZM2", "INC2"] if has_backsights else [])
    if cols[: len(expected)] != expected:
        raise ParseError(
            file, ln(hdr_idx),
            f"unexpected column header {cols!r} (expected {expected} [FLAGS COMMENTS])",
        )

    shots: list[CompassShot] = []
    n_numeric = 7 + (2 if has_backsights else 0)
    for i in range(hdr_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        shots.append(_parse_shot(line, n_numeric, has_backsights, file=file, line_no=ln(i)))

    return CompassSurvey(
        cave_name=cave_name,
        name=name,
        date_raw=date_raw,
        comment=comment,
        team=team,
        declination_deg=float(m["decl"]),
        format=fmt,
        corrections=corrections,
        corrections2=corrections2,
        discovery_raw=(m["disc"].strip() if m["disc"] else None),
        has_backsight_columns=has_backsights,
        shots=tuple(shots),
        source_file=file,
    )


def _parse_shot(
    line: str, n_numeric: int, has_backsights: bool, *, file: str, line_no: int
) -> CompassShot:
    parts = line.split(None, 2 + n_numeric)
    if len(parts) < 2 + n_numeric:
        raise ParseError(file, line_no, f"shot line has too few fields: {line.strip()!r}")
    frm, to = parts[0], parts[1]
    try:
        nums = [float(x) for x in parts[2 : 2 + n_numeric]]
    except ValueError as e:
        raise ParseError(file, line_no, f"non-numeric shot value: {e}") from e
    length, bearing, inc, left, up, down, right = nums[:7]
    azm2 = inc2 = None
    if has_backsights:
        azm2 = None if nums[7] <= _BACKSIGHT_SENTINEL else nums[7]
        inc2 = None if nums[8] <= _BACKSIGHT_SENTINEL else nums[8]

    flags = ShotFlags()
    comment = ""
    if len(parts) > 2 + n_numeric:
        rest = parts[2 + n_numeric].strip()
        if rest.startswith("#|"):
            end = rest.find("#", 2)
            if end == -1:
                raise ParseError(file, line_no, f"unterminated flags token: {rest!r}")
            flags = ShotFlags.parse(rest[: end + 1])
            comment = rest[end + 1 :].strip()
        else:
            comment = rest

    def lrud(v: float) -> float | None:
        return None if v <= _LRUD_SENTINEL else v

    return CompassShot(
        from_station=frm,
        to_station=to,
        length_ft=length,
        bearing_deg=bearing,
        inclination_deg=inc,
        left_ft=lrud(left),
        up_ft=lrud(up),
        down_ft=lrud(down),
        right_ft=lrud(right),
        azm2_deg=azm2,
        inc2_deg=inc2,
        flags=flags,
        comment=comment,
        line_no=line_no,
    )
