"""Parser for Compass .mak project files. Stdlib only."""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from speleoconvert.compass.model import (
    CompassProject,
    DatLink,
    FixedStation,
    ParseError,
)
from speleoconvert.compass.parser_dat import parse_dat

_STATION_RE = re.compile(
    r"\s*(?P<name>[^,\[\]]+?)\s*\[\s*(?P<unit>[fm])\s*,"
    r"\s*(?P<x>-?[\d.]+)\s*,\s*(?P<y>-?[\d.]+)\s*,\s*(?P<z>-?[\d.]+)\s*\]\s*",
    re.IGNORECASE,
)


def _split_station_entries(rest: str) -> list[str]:
    """Split a link's station list on commas that are outside [brackets]."""
    entries: list[str] = []
    depth, cur = 0, ""
    for ch in rest:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            entries.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        entries.append(cur)
    return entries


def parse_mak(path: str | Path) -> CompassProject:
    path = Path(path)
    try:
        text = path.read_bytes().decode("cp437")
    except UnicodeDecodeError as e:
        raise ParseError(str(path), 0, f"undecodable byte: {e}") from e
    text = text.replace("\x1a", "")

    base = None
    file_datum: str | None = None
    cur_datum: str | None = None
    cur_zone: int | None = None
    flags_raw: str | None = None
    comments: list[str] = []
    pending_params: list[str] = []
    links: list[DatLink] = []

    # split into statements: comments are whole lines starting with '/',
    # everything else accumulates until ';'
    statements: list[tuple[int, str]] = []  # (line_no, stmt)
    buf, buf_line = "", 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("/"):
            if buf:
                raise ParseError(
                    str(path), line_no,
                    "comment line inside an unterminated statement (would be "
                    f"swallowed into {buf[:40]!r})")
            comments.append(stripped)
            continue
        if not stripped and not buf:
            continue
        if not buf:
            buf_line = line_no
        buf += (" " if buf else "") + stripped
        while ";" in buf:
            stmt, buf = buf.split(";", 1)
            buf = buf.strip()
            statements.append((buf_line, stmt.strip()))
            buf_line = line_no
    if buf.strip():
        raise ParseError(str(path), buf_line, f"unterminated statement: {buf.strip()!r}")

    for line_no, stmt in statements:
        if not stmt:
            continue
        head, body = stmt[0], stmt[1:]
        if head == "@":
            vals = [v.strip() for v in body.split(",")]
            if len(vals) != 5:
                raise ParseError(str(path), line_no, f"bad base location: {stmt!r}")
            try:
                base = (float(vals[0]), float(vals[1]), float(vals[2]),
                        int(vals[3]), float(vals[4]))
            except ValueError as e:
                raise ParseError(str(path), line_no,
                                 f"bad base location value: {e}") from e
        elif head == "&":
            cur_datum = body.strip()
            if file_datum is None:
                file_datum = cur_datum
        elif head == "$":
            try:
                cur_zone = int(body.strip())
            except ValueError as e:
                raise ParseError(str(path), line_no,
                                 f"bad UTM zone {body.strip()!r}") from e
        elif head == "!":
            if flags_raw is None:
                flags_raw = body.strip()
            else:
                pending_params.append(stmt)
        elif head in ("*", "%"):
            pending_params.append(stmt)
        elif head == "#":
            fname, _, rest = body.partition(",")
            stations: list[FixedStation] = []
            link_stations: list[str] = []
            if rest.strip():
                for entry in _split_station_entries(rest):
                    m = _STATION_RE.fullmatch(entry)
                    if m:
                        stations.append(
                            FixedStation(
                                name=m["name"].strip(),
                                unit=m["unit"].lower(),
                                x=float(m["x"]),
                                y=float(m["y"]),
                                z=float(m["z"]),
                                raw=entry.strip(),
                            )
                        )
                    elif entry.strip() and "[" not in entry:
                        # bare station name: a link station without coordinates
                        link_stations.append(entry.strip())
                    else:
                        raise ParseError(
                            str(path), line_no, f"bad fixed station near {entry[:40]!r}"
                        )
            links.append(
                DatLink(
                    path=fname.strip(),
                    datum=cur_datum,
                    utm_zone=cur_zone,
                    fixed_stations=tuple(stations),
                    link_stations=tuple(link_stations),
                    raw_params=tuple(pending_params),
                )
            )
            pending_params = []
        else:
            raise ParseError(str(path), line_no, f"unknown .mak directive: {stmt!r}")

    if not links:
        raise ParseError(str(path), 0, "no #linked .dat files")

    return CompassProject(
        mak_path=str(path),
        base_easting_m=base[0] if base else None,
        base_northing_m=base[1] if base else None,
        base_elevation_m=base[2] if base else None,
        base_zone=base[3] if base else None,
        convergence_deg=base[4] if base else None,
        datum=file_datum,
        flags_raw=flags_raw,
        comments=tuple(comments),
        links=tuple(links),
    )


def _resolve_case_insensitive(directory: Path, name: str) -> Path | None:
    cand = directory / name
    if cand.exists():
        return cand
    lower = name.lower()
    for p in directory.iterdir():
        if p.name.lower() == lower:
            return p
    return None


def load_project(mak_path: str | Path) -> CompassProject:
    mak_path = Path(mak_path)
    project = parse_mak(mak_path)
    dat_files = []
    for link in project.links:
        resolved = _resolve_case_insensitive(mak_path.parent, link.path)
        if resolved is None:
            raise ParseError(str(mak_path), 0, f"linked file not found: {link.path!r}")
        dat_files.append(parse_dat(resolved))
    return replace(project, dat_files=tuple(dat_files))
