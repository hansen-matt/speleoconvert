"""Faithful, frozen, stdlib-only model of Compass survey data."""
from __future__ import annotations

from dataclasses import dataclass, field

AZIMUTH_UNITS = frozenset("DQR")       # degrees, quads, grads
LENGTH_UNITS = frozenset("DIM")        # decimal feet, feet+inches, meters
INCLINATION_UNITS = frozenset("DGMWR")  # degrees, %grade, deg+min, depth-gauge, grads


class ParseError(Exception):
    def __init__(self, file: str, line_no: int, message: str) -> None:
        self.file, self.line_no, self.message = file, line_no, message
        super().__init__(f"{file}:{line_no}: {message}")


@dataclass(frozen=True)
class ShotFlags:
    exclude_length: bool = False  # L
    exclude_plot: bool = False    # P
    exclude_all: bool = False     # X
    no_adjust: bool = False       # C
    raw: str = ""

    @classmethod
    def parse(cls, token: str) -> ShotFlags:
        inner = token.removeprefix("#|").removesuffix("#")
        return cls(
            exclude_length="L" in inner,
            exclude_plot="P" in inner,
            exclude_all="X" in inner,
            no_adjust="C" in inner,
            raw=inner,
        )


@dataclass(frozen=True)
class FormatSpec:
    raw: str
    azimuth_unit: str
    length_unit: str
    lrud_unit: str
    inclination_unit: str
    lrud_order: str
    item_order: str
    backsight_flag: str      # 'B' or 'N'
    lrud_association: str    # 'F' or 'T'

    @classmethod
    def parse(cls, raw: str, *, file: str, line_no: int) -> FormatSpec:
        def fail(msg: str) -> ParseError:
            return ParseError(file, line_no, f"FORMAT {raw!r}: {msg}")

        if len(raw) < 11:
            raise fail("too short")
        az, ln, pa, inc = raw[0], raw[1], raw[2], raw[3]
        if az not in AZIMUTH_UNITS:
            raise fail(f"unknown azimuth unit {az!r}")
        if ln not in LENGTH_UNITS:
            raise fail(f"unknown length unit {ln!r}")
        if pa not in LENGTH_UNITS:
            raise fail(f"unknown passage unit {pa!r}")
        if inc not in INCLINATION_UNITS:
            raise fail(f"unknown inclination unit {inc!r}")
        lrud_order = raw[4:8]
        if sorted(lrud_order) != ["D", "L", "R", "U"]:
            raise fail(f"bad LRUD order {lrud_order!r}")
        rest = raw[8:]
        assoc = "F"
        if rest and rest[-1] in "FT":
            assoc, rest = rest[-1], rest[:-1]
        backsight = "N"
        if rest and rest[-1] in "BN":
            backsight, rest = rest[-1], rest[:-1]
        if sorted(rest) not in (["A", "D", "L"], ["A", "D", "L", "a", "d"]):
            raise fail(f"bad item order {rest!r}")
        return cls(raw, az, ln, pa, inc, lrud_order, rest, backsight, assoc)


@dataclass(frozen=True)
class CompassShot:
    from_station: str
    to_station: str
    length_ft: float
    bearing_deg: float | None
    inclination_deg: float | None
    left_ft: float | None
    up_ft: float | None
    down_ft: float | None
    right_ft: float | None
    azm2_deg: float | None = None
    inc2_deg: float | None = None
    flags: ShotFlags = field(default_factory=ShotFlags)
    comment: str = ""
    line_no: int = 0


@dataclass(frozen=True)
class CompassSurvey:
    cave_name: str
    name: str
    date_raw: str
    comment: str
    team: tuple[str, ...]
    declination_deg: float
    format: FormatSpec
    corrections: tuple[float, float, float] | None
    corrections2: tuple[float, float] | None
    discovery_raw: str | None
    has_backsight_columns: bool
    shots: tuple[CompassShot, ...]
    source_file: str


@dataclass(frozen=True)
class CompassDatFile:
    path: str
    surveys: tuple[CompassSurvey, ...]


@dataclass(frozen=True)
class FixedStation:
    name: str
    unit: str  # 'f' feet | 'm' meters
    x: float
    y: float
    z: float
    raw: str


@dataclass(frozen=True)
class DatLink:
    path: str
    datum: str | None
    utm_zone: int | None
    fixed_stations: tuple[FixedStation, ...] = ()
    link_stations: tuple[str, ...] = ()  # bare station names, no coordinates
    raw_params: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompassProject:
    mak_path: str
    base_easting_m: float | None
    base_northing_m: float | None
    base_elevation_m: float | None
    base_zone: int | None
    convergence_deg: float | None
    datum: str | None
    flags_raw: str | None
    comments: tuple[str, ...]
    links: tuple[DatLink, ...]
    dat_files: tuple[CompassDatFile, ...] = ()
