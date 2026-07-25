# speleoconvert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lossless converter from Fountainware Compass projects (`.mak` + `.dat`s) to Ariane's Line `.tml`, as a Python library + CLI.

**Architecture:** Pure-stdlib Compass parsers feed frozen dataclasses; `mapping.py` turns a `CompassProject` into a plain Python dict (the openspeleo survey shape); only `ariane_writer.py` imports `openspeleo-lib` to validate + write the `.tml`. `pyproj` converts `.mak` fixed stations (UTM + datum) to WGS84. Every non-native mapping lands in the shot/section comment (lenient) or raises (strict), and always lands in a JSON+text conversion report.

**Tech Stack:** Python ≥3.11, uv project, `openspeleo-lib>=0.0.18`, `pyproj>=3.6`, pytest, ruff.

## Global Constraints

- Repo: `/home/confuted/git/speleoconvert` (already exists, has `docs/`; spec at `docs/superpowers/specs/2026-07-25-compass-to-ariane-design.md`).
- `src/` layout. Package name `speleoconvert`. CLI entry point `speleoconvert`.
- **Only `src/speleoconvert/ariane_writer.py` may import `openspeleo_lib`.** Everything else stdlib (+`pyproj` in `geodesy.py` only). Enforced by a test.
- **Real survey data is never committed** (cave locations are sensitive). Corpus tests read `SPELEOCONVERT_CORPUS` env var (points at `~/.claude/jobs/3f4f5047/tmp/samples/cave survey` or wherever the user unpacked it) and `pytest.skip` if unset.
- Parse errors are always fatal with `file:line` context. Never guess, never silently drop.
- Values on disk are **always decimal feet and degrees** regardless of FORMAT string (verified across corpus; FORMAT is display metadata). The geometry-verification task cross-checks this per project.
- All 850 survey headers in the corpus use fixed column order `FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS`; the parser validates the header line and hard-errors on deviation (backsight columns `AZM2 INC2` are detected via the header when present).
- Files are cp437, CRLF, `\x0c` between surveys, optional trailing `\x1a`.
- Commit after every task (repo is fresh; keep messages `feat:`/`test:`/`chore:`).
- Run tests with `uv run pytest -q` from the repo root.

## Verified openspeleo-lib API (pinned by spike, 2026-07-25, v0.0.18)

```python
from openspeleo_lib.interfaces.ariane.interface import ArianeSurvey, ArianeInterface
from openspeleo_lib.generators import UniqueValueGenerator

with UniqueValueGenerator.activate_uniqueness():
    survey = ArianeSurvey.model_validate(data_dict)   # plain dict, python field names
ArianeInterface.to_file(survey, Path("out.tml"))      # writes zip w/ Data.xml
back = ArianeInterface.from_file("out.tml")           # round-trip reader
```

- Shot chaining is by **global integer IDs**: `id_stop` (this shot's ID), `id_start` (previous shot's ID, `-1` for roots), `closure_to_id` (loop closure target, `-1` otherwise). Station name goes in `Shot.name` (= TO station).
- `shot_type`: `"START"` (component root, length 0), `"REAL"`, `"CLOSURE"` (loop-closing shot).
- Section dicts REQUIRE `"survey": None`, `"section": None` on shots (excluded parent refs), and `explorers`/`surveyors` MUST be lists (never None — `ariane_encode` crashes).
- LRUD `None` serializes as `<Left/>` and round-trips as `None`. LRUD values must be ≥ 0.
- `unit`: `"FT"` or `"M"`. `date`: ISO string `"2024-02-23"` or None (but None becomes `<Date/>`; fine).
- `correction`: list of 3 floats, `correction2`: list of 2, `declination`: float, `compass_format`: str — all on Section.

## Compass format facts (verified against 25-project corpus)

`.dat` survey block:
```
<cave name>
SURVEY NAME: <name>
SURVEY DATE: 8 11 2010  COMMENT:<optional text>
SURVEY TEAM:
<comma-separated names, or "?" or blank>
DECLINATION:   -4.81  FORMAT: DDDWUDLRDALadNF  CORRECTIONS:  0.00 0.00 0.00  CORRECTIONS2:  0.00 0.00  DISCOVERY: 9 24 2024
<blank>
<column header>
<blank>
<shot lines>
```
`CORRECTIONS`, `CORRECTIONS2`, `DISCOVERY` are each optional (older files lack them).
FORMAT string: chars 0-3 = units (azimuth `DQR`, length `DIM`, passage `DIM`, inclination `DGMWR`); chars 4-7 = LRUD display permutation; remainder = item display order (`LAD` + optional `a`,`d` backsight items), then `B|N`, then optional `F|T` (LRUD tied to From/To station). Corpus variants include `DDDWLRUDLAaDdNF`, `DDDWUDRLLADN`, `DMMDLRUDLADNT`, `DIDWUDRLLAaDdNF`, `DDDWLRUDLDAN`.
Sentinels: LRUD `-9.90` (and `-999.25`) = absent; backsight `AZM2`/`INC2` `-999.25` = absent.
Flags token: `#|<letters>#` where `L`=exclude-from-length, `P`=exclude-from-plot, `X`=exclude-totally, `C`=don't-adjust. Comment = rest of line.

`.mak` statements end with `;`, `/`-prefixed lines are comments/separators:
```
@284551.100,3373992.300,0.000,17,-1.140;   base location (UTM meters, zone, convergence)
&WGS 1984;                                  datum (state, may repeat per-link)
!gEvotScxpl;                                display/processing flags (preserve verbatim)
$17;                                        UTM zone (state)
*0.00;                                      unknown param (preserve verbatim, report)
#Region_1.DAT,                              linked file + optional fixed stations
 1E5[f,933560.866,11070112.205,0.000],
 MZ0[f,932973.668,11069885.496,0.000];
```
Fixed-station unit flag: `f`=feet, `m`=meters. Datums seen: `WGS 1984`, `North American 1927`, `North American 1983`.
EPSG: NAD27 UTM = 26700+zone, NAD83 = 26900+zone, WGS84 = 32600+zone (northern hemisphere). Feet→meters ×0.3048 (international foot; documented decision).

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/speleoconvert/__init__.py`, `src/speleoconvert/cli.py`, `tests/test_cli.py`, `.gitignore`, `ruff.toml`

**Interfaces:**
- Produces: installable package; `speleoconvert --version` prints version; `main(argv) -> int` in `cli.py`.

- [ ] **Step 1: Write files**

`pyproject.toml`:
```toml
[project]
name = "speleoconvert"
version = "0.1.0"
description = "Lossless Fountainware Compass to Ariane's Line survey converter"
requires-python = ">=3.11"
dependencies = ["openspeleo-lib>=0.0.18", "pyproj>=3.6"]

[project.scripts]
speleoconvert = "speleoconvert.cli:entrypoint"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`src/speleoconvert/__init__.py`:
```python
__version__ = "0.1.0"
```

`src/speleoconvert/cli.py`:
```python
from __future__ import annotations

import sys

from speleoconvert import __version__


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--version" in argv:
        print(f"speleoconvert {__version__}")
        return 0
    print("usage: speleoconvert convert <project.mak> [options]", file=sys.stderr)
    return 2


def entrypoint() -> None:
    raise SystemExit(main())
```

`.gitignore`:
```
__pycache__/
*.egg-info/
.venv/
dist/
*.tml
*.report.json
```

`ruff.toml`:
```toml
line-length = 100
[lint]
select = ["E", "F", "I", "UP", "B"]
```

`tests/test_cli.py`:
```python
from speleoconvert.cli import main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "speleoconvert" in capsys.readouterr().out


def test_no_args_is_usage_error(capsys):
    assert main([]) == 2
```

- [ ] **Step 2: Run tests**

Run: `cd /home/confuted/git/speleoconvert && uv run pytest -q`
Expected: `2 passed`

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: scaffold speleoconvert package"
```

---

### Task 2: Pin the openspeleo-lib write API with a round-trip test

**Files:**
- Create: `src/speleoconvert/ariane_writer.py`, `tests/test_ariane_writer.py`, `tests/test_firewall.py`

**Interfaces:**
- Produces: `write_tml(survey_dict: dict, out_path: Path) -> None` and `read_tml(path: Path)` (returns openspeleo Survey, for tests/validation only). `survey_dict` is the plain-dict shape shown in the Global Constraints spike section.

- [ ] **Step 1: Write the failing tests**

`tests/test_ariane_writer.py`:
```python
import zipfile
from pathlib import Path

from speleoconvert.ariane_writer import read_tml, write_tml


def _minimal_survey() -> dict:
    return {
        "name": "spike",
        "unit": "FT",
        "first_start_absolute_elevation": 10.0,
        "use_magnetic_azimuth": True,
        "sections": [
            {
                "name": "S1",
                "survey": None,
                "date": "2024-02-23",
                "explorers": [],
                "surveyors": ["Matt Hansen"],
                "declination": -6.13,
                "compass_format": "DDDWLRUDLAaDdNF",
                "correction": [0.0, 0.0, 0.0],
                "correction2": [0.0, 0.0],
                "shots": [
                    {
                        "id_stop": 0, "section": None, "shot_type": "START",
                        "name": "ENTRANCE", "length": 0.0, "depth": 0.0,
                        "azimuth": 0.0, "latitude": 30.1, "longitude": -83.2,
                    },
                    {
                        "id_start": 0, "id_stop": 1, "section": None, "name": "L1",
                        "length": 110.0, "depth": 3.0, "depth_start": 0.0,
                        "azimuth": 338.0, "inclination": 1.56,
                        "right": 8.0, "up": 3.0, "down": 3.0, "left": None,
                        "comment": "hello",
                    },
                ],
            }
        ],
    }


def test_write_and_reread(tmp_path: Path):
    out = tmp_path / "out.tml"
    write_tml(_minimal_survey(), out)
    with zipfile.ZipFile(out) as z:
        assert "Data.xml" in z.namelist()
        xml = z.read("Data.xml").decode()
    assert "<caveName>spike</caveName>" in xml
    assert "<unit>ft</unit>" in xml
    back = read_tml(out)
    shot = back.sections[0].shots[1]
    assert shot.name == "L1"
    assert shot.left is None          # absent LRUD round-trips as absent
    assert shot.length == 110.0
    assert back.sections[0].surveyors == ["Matt Hansen"]
```

`tests/test_firewall.py`:
```python
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "speleoconvert"


def test_only_ariane_writer_imports_openspeleo():
    offenders = [
        p for p in SRC.rglob("*.py")
        if "openspeleo" in p.read_text() and p.name != "ariane_writer.py"
    ]
    assert offenders == []


def test_compass_package_is_stdlib_only():
    code = (
        "import sys; mods_before=set(sys.modules); "
        "import speleoconvert.compass.model, speleoconvert.compass.parser_dat, "
        "speleoconvert.compass.parser_mak; "
        "bad=[m for m in sys.modules if m.split('.')[0] in "
        "('openspeleo_lib','pyproj','pydantic','orjson')]; "
        "assert not bad, bad"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```
(The second test will fail until Task 3 creates the `compass` package — mark it `@pytest.mark.xfail(reason="compass package lands in Task 3")` for this task's commit and remove the marker in Task 3.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ariane_writer.py -q`
Expected: FAIL — `ModuleNotFoundError: speleoconvert.ariane_writer`

- [ ] **Step 3: Implement**

`src/speleoconvert/ariane_writer.py`:
```python
"""The ONLY module allowed to import openspeleo_lib (see spec: firewall)."""
from __future__ import annotations

from pathlib import Path

from openspeleo_lib.generators import UniqueValueGenerator
from openspeleo_lib.interfaces.ariane.interface import ArianeInterface, ArianeSurvey


def write_tml(survey_dict: dict, out_path: Path) -> None:
    with UniqueValueGenerator.activate_uniqueness():
        survey = ArianeSurvey.model_validate(survey_dict)
    ArianeInterface.to_file(survey, Path(out_path))


def read_tml(path: Path):
    return ArianeInterface.from_file(Path(path))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass (firewall test xfail)

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: ariane_writer wrapping pinned openspeleo-lib API"
```

---

### Task 3: Compass data model

**Files:**
- Create: `src/speleoconvert/compass/__init__.py` (empty), `src/speleoconvert/compass/model.py`, `tests/test_model.py`
- Modify: `tests/test_firewall.py` (remove the xfail marker)

**Interfaces:**
- Produces (all frozen dataclasses, all consumed by parsers/mapping):
  - `ParseError(Exception)` with `file: str`, `line_no: int`, `message: str`
  - `ShotFlags(exclude_length, exclude_plot, exclude_all, no_adjust: bool, raw: str)`
  - `CompassShot(from_station, to_station: str, length_ft: float, bearing_deg: float | None, inclination_deg: float | None, left_ft, up_ft, down_ft, right_ft: float | None, azm2_deg: float | None, inc2_deg: float | None, flags: ShotFlags, comment: str, line_no: int)`
  - `FormatSpec(raw, azimuth_unit, length_unit, lrud_unit, inclination_unit: str, lrud_order: str, item_order: str, backsight_flag: str, lrud_association: str)` with classmethod `parse(raw: str, *, file: str, line_no: int) -> FormatSpec`
  - `CompassSurvey(cave_name, name, date_raw, comment: str, team: tuple[str, ...], declination_deg: float, format: FormatSpec, corrections: tuple[float, float, float] | None, corrections2: tuple[float, float] | None, discovery_raw: str | None, has_backsight_columns: bool, shots: tuple[CompassShot, ...], source_file: str)`
  - `FixedStation(name: str, unit: str, x: float, y: float, z: float, raw: str)`
  - `DatLink(path: str, datum: str, utm_zone: int, fixed_stations: tuple[FixedStation, ...], raw_params: tuple[str, ...])`
  - `CompassProject(mak_path: str, base_easting_m, base_northing_m, base_elevation_m: float, base_zone: int, convergence_deg: float, datum: str, flags_raw: str | None, comments: tuple[str, ...], links: tuple[DatLink, ...], dat_files: tuple[CompassDatFile, ...])`
  - `CompassDatFile(path: str, surveys: tuple[CompassSurvey, ...])`

- [ ] **Step 1: Write the failing test**

`tests/test_model.py`:
```python
import pytest

from speleoconvert.compass.model import FormatSpec, ParseError, ShotFlags


@pytest.mark.parametrize(
    "raw,az,length,lrud,inc,order,items,bs,assoc",
    [
        ("DDDWLRUDLAaDdNF", "D", "D", "D", "W", "LRUD", "LAaDd", "N", "F"),
        ("DDDWUDRLLADN", "D", "D", "D", "W", "UDRL", "LAD", "N", "F"),
        ("DMMDLRUDLADNT", "D", "M", "M", "D", "LRUD", "LAD", "N", "T"),
        ("DIDWUDRLLAaDdNF", "D", "I", "D", "W", "UDRL", "LAaDd", "N", "F"),
        ("DDDWLRUDLDAN", "D", "D", "D", "W", "LRUD", "LDA", "N", "F"),
        ("DDDDUDRLLADN", "D", "D", "D", "D", "UDRL", "LAD", "N", "F"),
    ],
)
def test_format_spec_corpus_variants(raw, az, length, lrud, inc, order, items, bs, assoc):
    f = FormatSpec.parse(raw, file="x.dat", line_no=6)
    assert (f.azimuth_unit, f.length_unit, f.lrud_unit, f.inclination_unit) == (az, length, lrud, inc)
    assert f.lrud_order == order
    assert f.item_order == items
    assert f.backsight_flag == bs
    assert f.lrud_association == assoc
    assert f.raw == raw


@pytest.mark.parametrize("raw", ["DDDZLRUDLADN", "DDDWLXUDLADN", "DDDWLRUDQQQN", "SHORT"])
def test_format_spec_rejects_unknown(raw):
    with pytest.raises(ParseError) as e:
        FormatSpec.parse(raw, file="x.dat", line_no=6)
    assert "x.dat:6" in str(e.value)


def test_flags_parse():
    f = ShotFlags.parse("#|PC#")
    assert f.exclude_plot and f.no_adjust
    assert not f.exclude_length and not f.exclude_all
    assert f.raw == "PC"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_model.py -q`
Expected: FAIL — no module `speleoconvert.compass.model`

- [ ] **Step 3: Implement**

`src/speleoconvert/compass/model.py`:
```python
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
    datum: str
    utm_zone: int
    fixed_stations: tuple[FixedStation, ...] = ()
    raw_params: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompassProject:
    mak_path: str
    base_easting_m: float
    base_northing_m: float
    base_elevation_m: float
    base_zone: int
    convergence_deg: float
    datum: str
    flags_raw: str | None
    comments: tuple[str, ...]
    links: tuple[DatLink, ...]
    dat_files: tuple[CompassDatFile, ...] = ()
```

Also create empty `src/speleoconvert/compass/__init__.py` and remove the xfail marker in `tests/test_firewall.py` (the `parser_dat`/`parser_mak` imports in that test will still fail — create empty placeholder modules `parser_dat.py` and `parser_mak.py` containing only `"""Placeholder — implemented in Tasks 4/5."""` so the firewall test is meaningful now).

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass, no xfail

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Compass data model + FORMAT string decoding"
```

---

### Task 4: `.dat` parser

**Files:**
- Create: `src/speleoconvert/compass/parser_dat.py` (replaces placeholder), `tests/test_parser_dat.py`, `tests/fixtures/synthetic.dat` (written by the test setup below, cp437+CRLF, via a small helper in the test file)

**Interfaces:**
- Consumes: `model.py` classes.
- Produces: `parse_dat(path: str | Path) -> CompassDatFile` and `parse_dat_text(text: str, *, file: str) -> CompassDatFile`.

- [ ] **Step 1: Write the failing test**

`tests/test_parser_dat.py`:
```python
import pytest

from speleoconvert.compass.model import ParseError
from speleoconvert.compass.parser_dat import parse_dat, parse_dat_text

SURVEY_A = (
    "oubliette\r\n"
    "SURVEY NAME: oubliette\r\n"
    "SURVEY DATE: 2 23 2024  COMMENT:first dive\r\n"
    "SURVEY TEAM: \r\n"
    "Matt Hansen,J Doe\r\n"
    "DECLINATION:   -6.13  FORMAT: DDDWLRUDLAaDdNF  CORRECTIONS:  1.00 2.00 3.00  CORRECTIONS2:  4.00 5.00\r\n"
    "\r\n"
    "                FROM                   TO   LENGTH  BEARING      INC     LEFT       UP     DOWN    RIGHT   FLAGS  COMMENTS\r\n"
    "\r\n"
    "                  L1                   L2   110.00   338.00     1.56    -9.90     3.00     3.00     8.00\r\n"
    "                  L2                   L3    77.00   336.00     8.97    20.00     0.00     6.00    30.00  #|PC#  tricky spot\r\n"
)

SURVEY_B = (
    "oubliette\r\n"
    "SURVEY NAME: SIDE\r\n"
    "SURVEY DATE: 1 1 2001  COMMENT:\r\n"
    "SURVEY TEAM: \r\n"
    "?\r\n"
    "DECLINATION:    0.00  FORMAT: DDDDUDRLLADN\r\n"
    "\r\n"
    "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n"
    "\r\n"
    "                  S1                   S2    10.00    90.00     0.00     1.00     1.00     1.00     1.00\r\n"
)

TWO_SURVEYS = SURVEY_A + "\x0c" + SURVEY_B + "\x1a"


def test_parses_two_surveys():
    dat = parse_dat_text(TWO_SURVEYS, file="oubliette.DAT")
    assert len(dat.surveys) == 2
    a, b = dat.surveys
    assert a.cave_name == "oubliette"
    assert a.name == "oubliette"
    assert a.date_raw == "2 23 2024"
    assert a.comment == "first dive"
    assert a.team == ("Matt Hansen", "J Doe")
    assert a.declination_deg == -6.13
    assert a.corrections == (1.0, 2.0, 3.0)
    assert a.corrections2 == (4.0, 5.0)
    assert b.team == ()          # "?" means unknown
    assert b.corrections is None


def test_shot_fields_and_sentinels():
    dat = parse_dat_text(TWO_SURVEYS, file="oubliette.DAT")
    s1, s2 = dat.surveys[0].shots
    assert (s1.from_station, s1.to_station) == ("L1", "L2")
    assert s1.length_ft == 110.0 and s1.bearing_deg == 338.0
    assert s1.left_ft is None            # -9.90 sentinel
    assert s1.up_ft == 3.0 and s1.down_ft == 3.0 and s1.right_ft == 8.0
    assert s1.flags.raw == "" and s1.comment == ""
    assert s2.flags.exclude_plot and s2.flags.no_adjust
    assert s2.comment == "tricky spot"
    # column layout: header said LEFT UP DOWN RIGHT -> fields land accordingly
    assert dat.surveys[1].shots[0].left_ft == 1.0


def test_bad_header_is_parse_error():
    broken = TWO_SURVEYS.replace("LENGTH  BEARING", "BEARING  LENGTH", 1)
    with pytest.raises(ParseError) as e:
        parse_dat_text(broken, file="x.dat")
    assert "column header" in str(e.value)


def test_malformed_shot_line_reports_location():
    broken = SURVEY_A + "                  L9\r\n"
    with pytest.raises(ParseError) as e:
        parse_dat_text(broken, file="x.dat")
    assert "x.dat:" in str(e.value)


def test_backsight_columns_detected():
    bs = SURVEY_A.replace(
        "     LEFT       UP     DOWN    RIGHT   FLAGS",
        "     LEFT       UP     DOWN    RIGHT     AZM2     INC2   FLAGS",
    ).replace(
        "     3.00     3.00     8.00\r\n",
        "     3.00     3.00     8.00   158.00    -1.50\r\n",
    ).replace(
        "     0.00     6.00    30.00  #|PC#  tricky spot\r\n",
        "     0.00     6.00    30.00  -999.25  -999.25  #|PC#  tricky spot\r\n",
    )
    dat = parse_dat_text(bs, file="bs.dat")
    sv = dat.surveys[0]
    assert sv.has_backsight_columns
    assert sv.shots[0].azm2_deg == 158.0 and sv.shots[0].inc2_deg == -1.5
    assert sv.shots[1].azm2_deg is None and sv.shots[1].inc2_deg is None


def test_parse_dat_reads_cp437(tmp_path):
    p = tmp_path / "enc.dat"
    p.write_bytes(TWO_SURVEYS.encode("cp437"))
    dat = parse_dat(p)
    assert dat.path.endswith("enc.dat")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_parser_dat.py -q`
Expected: FAIL — `parse_dat_text` not defined (placeholder module)

- [ ] **Step 3: Implement**

`src/speleoconvert/compass/parser_dat.py`:
```python
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

    cave_name = _get(lines, 0, file, line_offset, "cave name").strip()

    name_line = _get(lines, 1, file, line_offset, "SURVEY NAME")
    if "SURVEY NAME:" not in name_line:
        raise ParseError(file, ln(1), f"expected SURVEY NAME, got {name_line!r}")
    name = name_line.split("SURVEY NAME:", 1)[1].strip()

    date_line = _get(lines, 2, file, line_offset, "SURVEY DATE")
    if "SURVEY DATE:" not in date_line:
        raise ParseError(file, ln(2), f"expected SURVEY DATE, got {date_line!r}")
    date_part = date_line.split("SURVEY DATE:", 1)[1]
    if "COMMENT:" in date_part:
        date_raw, comment = date_part.split("COMMENT:", 1)
    else:
        date_raw, comment = date_part, ""
    date_raw, comment = date_raw.strip(), comment.strip()

    team_hdr = _get(lines, 3, file, line_offset, "SURVEY TEAM")
    if "SURVEY TEAM:" not in team_hdr:
        raise ParseError(file, ln(3), f"expected SURVEY TEAM, got {team_hdr!r}")
    team_line = _get(lines, 4, file, line_offset, "team names").strip()
    team: tuple[str, ...] = ()
    if team_line and team_line != "?":
        team = tuple(t.strip() for t in team_line.split(",") if t.strip())

    decl_line = _get(lines, 5, file, line_offset, "DECLINATION")
    m = _DECL_RE.search(decl_line)
    if not m:
        raise ParseError(file, ln(5), f"cannot parse DECLINATION line: {decl_line!r}")
    fmt = FormatSpec.parse(m["fmt"], file=file, line_no=ln(5))
    corrections = None
    if m["c1"] is not None:
        corrections = (float(m["c1"]), float(m["c2"]), float(m["c3"]))
    corrections2 = None
    if m["d1"] is not None:
        corrections2 = (float(m["d1"]), float(m["d2"]))

    # find column header row
    hdr_idx = None
    for i in range(6, len(lines)):
        if "FROM" in lines[i] and "TO" in lines[i] and "LENGTH" in lines[i]:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ParseError(file, ln(6), "missing shot column header row")
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Sanity-run against a real file and commit**

Run: `uv run python -c "
from speleoconvert.compass.parser_dat import parse_dat
d = parse_dat('$SPELEOCONVERT_CORPUS/oubliette/oubliette.DAT')
print(len(d.surveys), 'surveys', sum(len(s.shots) for s in d.surveys), 'shots')"`
(set `SPELEOCONVERT_CORPUS` first; expect no exception)

```bash
git add -A && git commit -m "feat: lossless .dat parser"
```

---

### Task 5: `.mak` parser

**Files:**
- Create: `src/speleoconvert/compass/parser_mak.py` (replaces placeholder), `tests/test_parser_mak.py`

**Interfaces:**
- Consumes: `model.py`.
- Produces: `parse_mak(path: str | Path) -> CompassProject` (does NOT load `.dat`s) and `load_project(mak_path: str | Path) -> CompassProject` (parses `.mak`, resolves each link's `.dat` case-insensitively relative to the `.mak` dir, parses them, returns project with `dat_files` populated; missing file → `ParseError`).

- [ ] **Step 1: Write the failing test**

`tests/test_parser_mak.py`:
```python
import pytest

from speleoconvert.compass.model import ParseError
from speleoconvert.compass.parser_mak import parse_mak, load_project

MAK = (
    "@284551.100,3373992.300,0.000,17,-1.140;\r\n"
    "&WGS 1984;\r\n"
    "!gEvotScxpl;\r\n"
    "\r\n"
    "/\r\n"
    "$17;\r\n"
    "&North American 1927;\r\n"
    "*0.00;\r\n"
    "#Region_1.DAT,\r\n"
    " 1E5[f,933560.866,11070112.205,0.000],\r\n"
    " MZ0[m,284000.0,3373000.0,1.5];\r\n"
    "/ a trailing comment\r\n"
    "*0.00;\r\n"
    "#M3 Data.dat;\r\n"
)


def _write(tmp_path, text=MAK):
    p = tmp_path / "test.MAK"
    p.write_bytes(text.encode("cp437"))
    return p


def test_parse_mak_base_and_links(tmp_path):
    prj = parse_mak(_write(tmp_path))
    assert prj.base_easting_m == 284551.1
    assert prj.base_zone == 17
    assert prj.convergence_deg == -1.14
    assert prj.datum == "WGS 1984"
    assert prj.flags_raw == "gEvotScxpl"
    assert len(prj.links) == 2
    l1, l2 = prj.links
    assert l1.path == "Region_1.DAT"
    assert l1.datum == "North American 1927"   # per-link datum override
    assert l1.utm_zone == 17
    assert [f.name for f in l1.fixed_stations] == ["1E5", "MZ0"]
    assert l1.fixed_stations[0].unit == "f"
    assert l1.fixed_stations[1].unit == "m"
    assert l1.fixed_stations[1].z == 1.5
    assert l1.raw_params == ("*0.00",)
    assert l2.path == "M3 Data.dat"
    assert l2.fixed_stations == ()
    assert any(c.startswith("/") for c in prj.comments)


def test_unknown_directive_is_error(tmp_path):
    with pytest.raises(ParseError):
        parse_mak(_write(tmp_path, MAK + "%bogus;\r\n"))


def test_load_project_resolves_case_insensitive(tmp_path):
    p = _write(tmp_path)
    dat = (
        "cave\r\nSURVEY NAME: A\r\nSURVEY DATE: 1 1 2020  COMMENT:\r\n"
        "SURVEY TEAM: \r\n\r\n"
        "DECLINATION: 0.00  FORMAT: DDDDUDRLLADN\r\n\r\n"
        "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n\r\n"
        "A1 A2 10.00 90.00 0.00 1.00 1.00 1.00 1.00\r\n"
    )
    # note different case vs link names
    (tmp_path / "REGION_1.dat").write_bytes(dat.encode("cp437"))
    (tmp_path / "m3 data.DAT").write_bytes(dat.encode("cp437"))
    prj = load_project(p)
    assert len(prj.dat_files) == 2
    assert prj.dat_files[0].surveys[0].name == "A"


def test_load_project_missing_dat_is_error(tmp_path):
    with pytest.raises(ParseError) as e:
        load_project(_write(tmp_path))
    assert "Region_1.DAT" in str(e.value)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_parser_mak.py -q`
Expected: FAIL — functions not defined

- [ ] **Step 3: Implement**

`src/speleoconvert/compass/parser_mak.py`:
```python
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
        if not buf and stripped.startswith("/"):
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
        head, body = stmt[0], stmt[1:]
        if head == "@":
            vals = [v.strip() for v in body.split(",")]
            if len(vals) != 5:
                raise ParseError(str(path), line_no, f"bad base location: {stmt!r}")
            base = (float(vals[0]), float(vals[1]), float(vals[2]), int(vals[3]), float(vals[4]))
        elif head == "&":
            cur_datum = body.strip()
            if file_datum is None:
                file_datum = cur_datum
        elif head == "$":
            cur_zone = int(body.strip())
        elif head == "!":
            if flags_raw is None:
                flags_raw = body.strip()
            else:
                pending_params.append(stmt)
        elif head == "*":
            pending_params.append(stmt)
        elif head == "#":
            fname, _, rest = body.partition(",")
            stations = []
            if rest.strip():
                pos = 0
                while pos < len(rest):
                    m = _STATION_RE.match(rest, pos)
                    if not m:
                        raise ParseError(
                            str(path), line_no, f"bad fixed station near {rest[pos:pos+40]!r}"
                        )
                    stations.append(
                        FixedStation(
                            name=m["name"].strip(),
                            unit=m["unit"].lower(),
                            x=float(m["x"]),
                            y=float(m["y"]),
                            z=float(m["z"]),
                            raw=m.group(0).strip().rstrip(","),
                        )
                    )
                    pos = m.end()
                    if pos < len(rest) and rest[pos] == ",":
                        pos += 1
            if cur_datum is None or cur_zone is None:
                raise ParseError(
                    str(path), line_no, f"link {fname.strip()!r} before datum/zone declared"
                )
            links.append(
                DatLink(
                    path=fname.strip(),
                    datum=cur_datum,
                    utm_zone=cur_zone,
                    fixed_stations=tuple(stations),
                    raw_params=tuple(pending_params),
                )
            )
            pending_params = []
        else:
            raise ParseError(str(path), line_no, f"unknown .mak directive: {stmt!r}")

    if base is None:
        raise ParseError(str(path), 0, "missing @ base location")
    if file_datum is None:
        raise ParseError(str(path), 0, "missing & datum")
    if not links:
        raise ParseError(str(path), 0, "no #linked .dat files")

    return CompassProject(
        mak_path=str(path),
        base_easting_m=base[0],
        base_northing_m=base[1],
        base_elevation_m=base[2],
        base_zone=base[3],
        convergence_deg=base[4],
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: .mak parser + case-insensitive project loader"
```

---

### Task 6: Geodesy

**Files:**
- Create: `src/speleoconvert/geodesy.py`, `tests/test_geodesy.py`

**Interfaces:**
- Consumes: `FixedStation`, datum string, zone int.
- Produces: `fixed_station_to_wgs84(fs: FixedStation, zone: int, datum: str) -> tuple[float, float, float]` returning `(lat, lon, elevation_m)`; `class GeodesyError(Exception)`; `FT_TO_M = 0.3048`.

- [ ] **Step 1: Write the failing test**

`tests/test_geodesy.py`:
```python
import pytest

from speleoconvert.compass.model import FixedStation
from speleoconvert.geodesy import GeodesyError, fixed_station_to_wgs84


def test_wgs84_feet_station_matches_known_point():
    # MBSP entrance area, UTM 17N (WGS84): 933560.866 ft E, 11070112.205 ft N
    fs = FixedStation("1E5", "f", 933560.866, 11070112.205, 0.0, raw="")
    lat, lon, elev = fixed_station_to_wgs84(fs, zone=17, datum="WGS 1984")
    # ~Madison Blue Spring, FL
    assert lat == pytest.approx(30.48, abs=0.05)
    assert lon == pytest.approx(-83.24, abs=0.05)
    assert elev == 0.0


def test_meters_station_no_unit_conversion():
    f_ft = FixedStation("A", "f", 933560.866, 11070112.205, 0.0, raw="")
    f_m = FixedStation("A", "m", 933560.866 * 0.3048, 11070112.205 * 0.3048, 0.0, raw="")
    a = fixed_station_to_wgs84(f_ft, 17, "WGS 1984")
    b = fixed_station_to_wgs84(f_m, 17, "WGS 1984")
    assert a[0] == pytest.approx(b[0], abs=1e-9)
    assert a[1] == pytest.approx(b[1], abs=1e-9)


def test_nad27_differs_from_wgs84():
    fs = FixedStation("A", "f", 933560.866, 11070112.205, 0.0, raw="")
    w = fixed_station_to_wgs84(fs, 17, "WGS 1984")
    n = fixed_station_to_wgs84(fs, 17, "North American 1927")
    # NAD27->WGS84 shift in Florida is tens of meters, not zero, not huge
    dlat = abs(w[0] - n[0]) * 111_000
    assert 5 < dlat < 300


def test_unknown_datum_raises():
    fs = FixedStation("A", "f", 1.0, 1.0, 0.0, raw="")
    with pytest.raises(GeodesyError):
        fixed_station_to_wgs84(fs, 17, "Tokyo Datum")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_geodesy.py -q`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

`src/speleoconvert/geodesy.py`:
```python
"""UTM+datum -> WGS84 for Compass .mak fixed stations. Only module using pyproj."""
from __future__ import annotations

from functools import lru_cache

from pyproj import Transformer

from speleoconvert.compass.model import FixedStation

FT_TO_M = 0.3048  # international foot (documented decision; US-survey-foot delta ~2 ppm)

_DATUM_EPSG_BASE = {
    "WGS 1984": 32600,
    "North American 1983": 26900,
    "North American 1927": 26700,
}


class GeodesyError(Exception):
    pass


@lru_cache(maxsize=32)
def _transformer(datum: str, zone: int) -> Transformer:
    try:
        base = _DATUM_EPSG_BASE[datum]
    except KeyError:
        raise GeodesyError(
            f"unsupported datum {datum!r} (known: {sorted(_DATUM_EPSG_BASE)})"
        ) from None
    if not 1 <= zone <= 60:
        raise GeodesyError(f"bad UTM zone {zone}")
    return Transformer.from_crs(f"EPSG:{base + zone}", "EPSG:4326", always_xy=True)


def fixed_station_to_wgs84(
    fs: FixedStation, zone: int, datum: str
) -> tuple[float, float, float]:
    scale = FT_TO_M if fs.unit == "f" else 1.0
    x_m, y_m, z_m = fs.x * scale, fs.y * scale, fs.z * scale
    lon, lat = _transformer(datum, zone).transform(x_m, y_m)
    return lat, lon, z_m
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: geodesy for fixed stations (NAD27/NAD83/WGS84 UTM -> WGS84)"
```

---

### Task 7: Conversion report

**Files:**
- Create: `src/speleoconvert/report.py`, `tests/test_report.py`

**Interfaces:**
- Produces:
  - `Disposition` str-enum-ish constants: `NATIVE`, `COMMENT`, `REPORT_ONLY`, `ERROR`
  - `@dataclass ReportEntry(category: str, disposition: str, location: str, message: str)`
  - `class ConversionReport` with `.add(category, disposition, location, message)`, `.entries: list[ReportEntry]`, `.counts() -> dict[str, int]` (by category), `.non_native() -> list[ReportEntry]`, `.to_json() -> str` (includes tool version + input/output paths set via constructor `ConversionReport(source: str, output: str)`), `.summary_text() -> str` (human-readable, counts per category + every COMMENT/REPORT_ONLY entry)
  - `class StrictModeError(Exception)` carrying `entries: list[ReportEntry]`
- Strict-mode exemption set: `STRICT_EXEMPT_CATEGORIES = {"mak-display-flags", "mak-unknown-param", "mak-comment", "format-display-order", "lrud-missing"}` — display/UI preferences and ubiquitous sentinels; everything else with disposition != NATIVE raises in strict mode (enforced in Task 8's mapping, not here).

- [ ] **Step 1: Write the failing test**

`tests/test_report.py`:
```python
import json

from speleoconvert.report import (
    COMMENT,
    NATIVE,
    REPORT_ONLY,
    ConversionReport,
)


def test_report_collects_and_serializes():
    r = ConversionReport(source="a.mak", output="a.tml")
    r.add("backsight", COMMENT, "a.dat:12", "AZM2=158.0 INC2=-1.5 appended to comment")
    r.add("lrud-missing", REPORT_ONLY, "a.dat:10", "LEFT absent")
    r.add("shot", NATIVE, "a.dat:10", "ok")
    assert len(r.non_native()) == 2
    data = json.loads(r.to_json())
    assert data["source"] == "a.mak"
    assert data["counts"]["backsight"] == 1
    assert len(data["entries"]) == 3
    txt = r.summary_text()
    assert "backsight" in txt and "a.dat:12" in txt
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_report.py -q` — FAIL, module missing

- [ ] **Step 3: Implement**

`src/speleoconvert/report.py`:
```python
"""Conversion audit report: every non-native mapping decision, machine+human readable."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass

from speleoconvert import __version__

NATIVE = "native"
COMMENT = "comment"
REPORT_ONLY = "report-only"
ERROR = "error"

STRICT_EXEMPT_CATEGORIES = {
    "mak-display-flags",
    "mak-unknown-param",
    "mak-comment",
    "format-display-order",
    "lrud-missing",
}


@dataclass(frozen=True)
class ReportEntry:
    category: str
    disposition: str
    location: str
    message: str


class StrictModeError(Exception):
    def __init__(self, entries: list[ReportEntry]) -> None:
        self.entries = entries
        lines = "\n".join(f"  {e.location}: [{e.category}] {e.message}" for e in entries)
        super().__init__(
            f"{len(entries)} field(s) have no native Ariane equivalent "
            f"(rerun without --strict to embed them in comments):\n{lines}"
        )


class ConversionReport:
    def __init__(self, source: str, output: str) -> None:
        self.source, self.output = source, output
        self.entries: list[ReportEntry] = []

    def add(self, category: str, disposition: str, location: str, message: str) -> None:
        self.entries.append(ReportEntry(category, disposition, location, message))

    def non_native(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.disposition != NATIVE]

    def strict_violations(self) -> list[ReportEntry]:
        return [
            e for e in self.non_native() if e.category not in STRICT_EXEMPT_CATEGORIES
        ]

    def counts(self) -> dict[str, int]:
        return dict(Counter(e.category for e in self.entries))

    def to_json(self) -> str:
        return json.dumps(
            {
                "tool": f"speleoconvert {__version__}",
                "source": self.source,
                "output": self.output,
                "counts": self.counts(),
                "entries": [asdict(e) for e in self.entries],
            },
            indent=2,
        )

    def summary_text(self) -> str:
        lines = [f"speleoconvert report: {self.source} -> {self.output}"]
        for cat, n in sorted(self.counts().items()):
            lines.append(f"  {cat}: {n}")
        nn = self.non_native()
        if nn:
            lines.append("non-native mappings:")
            lines.extend(f"  {e.location}: [{e.category}] {e.message}" for e in nn)
        else:
            lines.append("all data mapped natively.")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests** — `uv run pytest -q`, all pass

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: conversion report with strict-mode violation tracking"
```

---

### Task 8: Mapping — CompassProject → Ariane survey dict

This is the heart. Pure python (no openspeleo import — output is a plain dict for `ariane_writer.write_tml`).

**Files:**
- Create: `src/speleoconvert/mapping.py`, `tests/test_mapping.py`

**Interfaces:**
- Consumes: `CompassProject` (with `dat_files`), `fixed_station_to_wgs84`, `ConversionReport`, `StrictModeError`.
- Produces: `map_project(project: CompassProject, *, strict: bool = False, report: ConversionReport) -> dict` (the survey dict). Raises `StrictModeError` when `strict` and `report.strict_violations()` is non-empty (checked once at the end, so the report is complete either way).

**Mapping rules (implement exactly):**
1. Survey name = `.mak` filename stem. `unit="FT"`. `use_magnetic_azimuth=True`. `first_start_absolute_elevation` = elevation (m) of the first fixed station, else 0.0.
2. One Section per `CompassSurvey`, in file order, `name` = survey name, `date` = ISO from `date_raw` ("2 23 2024" → "2024-02-23"; unparseable → `None` + report entry `survey-date`/COMMENT with the raw text appended to section comment), `explorers=[]`, `surveyors=list(team)`, `declination`, `compass_format=format.raw`, `correction=list(corrections or [0,0,0])`, `correction2=list(corrections2 or [0,0])`, `comment` = survey comment (+ `discovery_raw` appended as `Discovery: …` with report entry `survey-discovery`/COMMENT if present; + cave_name as `Cave: …` when cave_name differs from survey name — category `survey-cave-name`/COMMENT).
3. Shots get global integer IDs starting at 0. Walk sections in order, shots in file order:
   - Maintain `station_shot_id: dict[str, int]` (station name → ID of shot that first arrived there) and `station_depth: dict[str, float]`.
   - If `from_station` unseen: emit a START shot (`shot_type="START"`, `name=from_station`, `length=0.0`, `azimuth=0.0`, `depth=depth0`, id_start=-1) in the current section. `depth0` = 0.0, or for a fixed station, `-(z_m - z_ref)` where `z_ref` is the first fixed station's elevation. If the station is fixed, set `latitude`/`longitude` from `fixed_station_to_wgs84` and add report entry `fixed-station`/NATIVE.
   - Depth propagation: `depth_to = depth_from - length_ft * sin(radians(inclination))` (inclination `None` → treat 0.0 for depth math only, add report entry `inclination-missing`/REPORT_ONLY). Round to 4 decimals.
   - If `to_station` already seen: this is a loop-closing shot → `shot_type="CLOSURE"`, `closure_to_id=station_shot_id[to_station]`, and DON'T overwrite the station registry. Report entry `loop-closure`/NATIVE.
   - Otherwise REAL shot: `name=to_station`, `id_start=station_shot_id[from_station]`, `id_stop=<new id>`, register station.
   - `length=length_ft`, `azimuth=bearing_deg` (`None` → 0.0 + report `bearing-missing`/COMMENT), `inclination=inclination_deg`, `depth=depth_to`, `depth_start=depth_from`, LRUD passed through (`None` stays `None`; each absent one gets report entry `lrud-missing`/REPORT_ONLY).
   - Flags: `exclude_all` → `excluded=True` (NATIVE). `exclude_length`/`exclude_plot`/`no_adjust` → append `Compass flags: #|<raw>#` to shot comment + report `shot-flags`/COMMENT.
   - Backsights (`azm2_deg`/`inc2_deg` not None) → append `Backsight: azm2=<v> inc2=<v>` to comment + report `backsight`/COMMENT.
   - LRUD association `T` (at TO station) is Ariane-native behavior (Ariane LRUD describe the shot's end station); association `F` → report `format-display-order`/REPORT_ONLY noting LRUD were recorded at FROM station (data carried unchanged).
4. `.mak` leftovers: `flags_raw` → report `mak-display-flags`/REPORT_ONLY; each link's `raw_params` → `mak-unknown-param`/REPORT_ONLY; `comments` → `mak-comment`/REPORT_ONLY; `convergence_deg` → `mak-convergence`/REPORT_ONLY. Fixed stations that name a station never seen in any shot → `fixed-station-orphan`/COMMENT appended to the project-level first section comment.
5. Corrections are carried in Section fields, never applied to shot values.
6. At the end: `if strict and report.strict_violations(): raise StrictModeError(...)`.

- [ ] **Step 1: Write the failing test**

`tests/test_mapping.py`:
```python
import math

import pytest

from speleoconvert.compass.model import (
    CompassDatFile,
    CompassProject,
    CompassShot,
    CompassSurvey,
    DatLink,
    FixedStation,
    FormatSpec,
    ShotFlags,
)
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport, StrictModeError

FMT = FormatSpec.parse("DDDWLRUDLAaDdNF", file="t.dat", line_no=1)


def _shot(frm, to, length=10.0, bearing=90.0, inc=0.0, **kw):
    defaults = dict(
        left_ft=1.0, up_ft=1.0, down_ft=1.0, right_ft=1.0,
        azm2_deg=None, inc2_deg=None, flags=ShotFlags(), comment="", line_no=10,
    )
    defaults.update(kw)
    return CompassShot(frm, to, length, bearing, inc, **defaults)


def _project(shots, fixed=(), datum="WGS 1984"):
    survey = CompassSurvey(
        cave_name="cave", name="A", date_raw="2 23 2024", comment="hi",
        team=("Matt",), declination_deg=-6.13, format=FMT,
        corrections=(1.0, 2.0, 3.0), corrections2=(4.0, 5.0),
        discovery_raw=None, has_backsight_columns=False,
        shots=tuple(shots), source_file="t.dat",
    )
    return CompassProject(
        mak_path="/tmp/test.mak", base_easting_m=0, base_northing_m=0,
        base_elevation_m=0, base_zone=17, convergence_deg=-1.14,
        datum=datum, flags_raw="gEv", comments=(),
        links=(DatLink("t.dat", datum, 17, tuple(fixed)),),
        dat_files=(CompassDatFile("t.dat", (survey,)),),
    )


def test_basic_chain_and_ids():
    prj = _project([_shot("E", "S1", inc=-45.0, length=10.0), _shot("S1", "S2")])
    r = ConversionReport("s", "o")
    d = map_project(prj, report=r)
    sec = d["sections"][0]
    types = [s["shot_type"] for s in sec["shots"]]
    assert types == ["START", "REAL", "REAL"]
    start, s1, s2 = sec["shots"]
    assert start["name"] == "E" and start["id_stop"] == 0
    assert s1["id_start"] == 0 and s1["id_stop"] == 1 and s1["name"] == "S1"
    assert s1["depth"] == pytest.approx(10.0 * math.sin(math.radians(45.0)), abs=1e-3)
    assert s2["depth_start"] == s1["depth"]
    assert sec["declination"] == -6.13
    assert sec["correction"] == [1.0, 2.0, 3.0]
    assert sec["compass_format"] == "DDDWLRUDLAaDdNF"
    assert sec["date"] == "2024-02-23"
    assert d["unit"] == "FT"


def test_loop_becomes_closure():
    prj = _project([
        _shot("E", "A"), _shot("A", "B"), _shot("B", "E"),  # loop back to E
    ])
    d = map_project(prj, report=ConversionReport("s", "o"))
    last = d["sections"][0]["shots"][-1]
    assert last["shot_type"] == "CLOSURE"
    assert last["closure_to_id"] == 0  # E is the START shot, id 0


def test_fixed_station_gets_latlon():
    fixed = [FixedStation("E", "f", 933560.866, 11070112.205, 0.0, raw="")]
    prj = _project([_shot("E", "S1")], fixed=fixed)
    d = map_project(prj, report=ConversionReport("s", "o"))
    start = d["sections"][0]["shots"][0]
    assert start["latitude"] == pytest.approx(30.48, abs=0.05)
    assert start["longitude"] == pytest.approx(-83.24, abs=0.05)


def test_flags_and_backsights_to_comment_lenient():
    shots = [
        _shot("E", "S1", flags=ShotFlags(exclude_length=True, raw="L"), comment="c"),
        _shot("S1", "S2", azm2_deg=158.0, inc2_deg=-1.5),
    ]
    r = ConversionReport("s", "o")
    d = map_project(_project(shots), report=r)
    s1, s2 = d["sections"][0]["shots"][1:]
    assert "Compass flags: #|L#" in s1["comment"] and "c" in s1["comment"]
    assert "Backsight: azm2=158.0 inc2=-1.5" in s2["comment"]
    cats = {e.category for e in r.non_native()}
    assert {"shot-flags", "backsight"} <= cats


def test_strict_mode_raises_on_backsight():
    shots = [_shot("E", "S1", azm2_deg=158.0, inc2_deg=None)]
    with pytest.raises(StrictModeError):
        map_project(_project(shots), strict=True, report=ConversionReport("s", "o"))


def test_strict_mode_ok_for_exempt_categories():
    shots = [_shot("E", "S1", left_ft=None)]  # lrud-missing is exempt
    d = map_project(_project(shots), strict=True, report=ConversionReport("s", "o"))
    assert d["sections"][0]["shots"][1]["left"] is None


def test_excluded_flag_native():
    shots = [_shot("E", "S1", flags=ShotFlags(exclude_all=True, raw="X"))]
    d = map_project(_project(shots), strict=True, report=ConversionReport("s", "o"))
    assert d["sections"][0]["shots"][1]["excluded"] is True


def test_unparseable_date_goes_to_comment():
    prj = _project([_shot("E", "S1")])
    survey = prj.dat_files[0].surveys[0]
    object.__setattr__(survey, "date_raw", "1 1 1")  # frozen; test-only poke
    r = ConversionReport("s", "o")
    d = map_project(prj, report=r)
    sec = d["sections"][0]
    assert sec["date"] is None
    assert "1 1 1" in sec["comment"]
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_mapping.py -q`, FAIL (module missing)

- [ ] **Step 3: Implement**

`src/speleoconvert/mapping.py`:
```python
"""CompassProject -> Ariane survey dict (plain python; openspeleo-free)."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from speleoconvert.compass.model import CompassProject, CompassShot, CompassSurvey
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
                survey, project, fixed, z_ref, station_shot_id, station_depth,
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
    project: CompassProject,
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
```

- [ ] **Step 4: Run tests** — `uv run pytest -q`, all pass

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Compass->Ariane mapping with strict/lenient modes"
```

---

### Task 9: CLI `convert` command

**Files:**
- Modify: `src/speleoconvert/cli.py`
- Create: `tests/test_cli_convert.py`, `tests/fixtures/mini/` (mini project written by test setup: `mini.mak` + `mini.dat`, same synthetic content as Task 5's tests)

**Interfaces:**
- Produces: `speleoconvert convert <project.mak> [-o OUT.tml] [--strict] [--report PATH] [-q]`. Defaults: `OUT` = mak path with `.tml` suffix; report = `<OUT>.report.json`; summary printed to stdout unless `-q`. Exit codes: 0 ok, 1 conversion/strict error (message on stderr), 2 usage.

- [ ] **Step 1: Write the failing test**

`tests/test_cli_convert.py`:
```python
import json
from pathlib import Path

from speleoconvert.cli import main

MAK = (
    "@284551.100,3373992.300,0.000,17,-1.140;\r\n&WGS 1984;\r\n$17;\r\n"
    "#mini.dat,\r\n E[f,933560.866,11070112.205,0.000];\r\n"
)
DAT = (
    "cave\r\nSURVEY NAME: A\r\nSURVEY DATE: 2 23 2024  COMMENT:\r\n"
    "SURVEY TEAM: \r\nMatt\r\n"
    "DECLINATION: -6.13  FORMAT: DDDWLRUDLAaDdNF  CORRECTIONS: 0.00 0.00 0.00  CORRECTIONS2: 0.00 0.00\r\n"
    "\r\nFROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n\r\n"
    "E S1 100.00 90.00 -30.00 1.00 2.00 3.00 4.00\r\n"
    "S1 S2 50.00 180.00 0.00 -9.90 2.00 3.00 4.00\r\n"
)


def _mini(tmp_path: Path) -> Path:
    (tmp_path / "mini.mak").write_bytes(MAK.encode("cp437"))
    (tmp_path / "mini.dat").write_bytes(DAT.encode("cp437"))
    return tmp_path / "mini.mak"


def test_convert_end_to_end(tmp_path, capsys):
    mak = _mini(tmp_path)
    assert main(["convert", str(mak)]) == 0
    out = tmp_path / "mini.tml"
    assert out.exists()
    rep = json.loads((tmp_path / "mini.tml.report.json").read_text())
    assert rep["source"].endswith("mini.mak")
    # verify TML round-trips through openspeleo
    from speleoconvert.ariane_writer import read_tml
    back = read_tml(out)
    assert back.name == "mini"
    names = [s.name for s in back.sections[0].shots]
    assert names == ["E", "S1", "S2"]
    assert "speleoconvert report" in capsys.readouterr().out


def test_convert_strict_passes_clean_project(tmp_path):
    mak = _mini(tmp_path)
    assert main(["convert", str(mak), "--strict"]) == 0


def test_convert_strict_fails_flagged_project(tmp_path, capsys):
    (tmp_path / "mini.mak").write_bytes(MAK.encode("cp437"))
    flagged = DAT.replace(
        "S1 S2 50.00 180.00 0.00 -9.90 2.00 3.00 4.00",
        "S1 S2 50.00 180.00 0.00 -9.90 2.00 3.00 4.00  #|P#  low vis",
    )
    (tmp_path / "mini.dat").write_bytes(flagged.encode("cp437"))
    assert main(["convert", str(tmp_path / "mini.mak"), "--strict"]) == 1
    assert "no native Ariane equivalent" in capsys.readouterr().err


def test_convert_missing_file_exit_1(tmp_path, capsys):
    assert main(["convert", str(tmp_path / "nope.mak")]) == 1
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_cli_convert.py -q`, FAIL

- [ ] **Step 3: Implement**

Replace `src/speleoconvert/cli.py`:
```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from speleoconvert import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="speleoconvert",
        description="Lossless Fountainware Compass -> Ariane's Line converter",
    )
    parser.add_argument("--version", action="version", version=f"speleoconvert {__version__}")
    sub = parser.add_subparsers(dest="command")
    conv = sub.add_parser("convert", help="convert a Compass project (.mak) to .tml")
    conv.add_argument("mak", type=Path, help="Compass project file (.mak)")
    conv.add_argument("-o", "--output", type=Path, default=None, help=".tml output path")
    conv.add_argument("--strict", action="store_true",
                      help="error on any field without a native Ariane equivalent")
    conv.add_argument("--report", type=Path, default=None,
                      help="report path (default: <output>.report.json)")
    conv.add_argument("-q", "--quiet", action="store_true", help="suppress summary")

    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return int(e.code or 0)
    if args.command != "convert":
        parser.print_usage(sys.stderr)
        return 2
    return _convert(args)


def _convert(args: argparse.Namespace) -> int:
    # imports deferred so `--version`/usage never require heavy deps
    from speleoconvert.ariane_writer import write_tml
    from speleoconvert.compass.model import ParseError
    from speleoconvert.compass.parser_mak import load_project
    from speleoconvert.geodesy import GeodesyError
    from speleoconvert.mapping import map_project
    from speleoconvert.report import ConversionReport, StrictModeError

    out = args.output or args.mak.with_suffix(".tml")
    report_path = args.report or Path(f"{out}.report.json")
    report = ConversionReport(source=str(args.mak), output=str(out))
    try:
        project = load_project(args.mak)
        survey_dict = map_project(project, strict=args.strict, report=report)
        write_tml(survey_dict, out)
    except (ParseError, GeodesyError, StrictModeError, FileNotFoundError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    report_path.write_text(report.to_json())
    if not args.quiet:
        print(report.summary_text())
        print(f"wrote {out}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
```

Also update `tests/test_cli.py`: `main([])` now returns 2 via usage path and `--version` exits 0 through argparse — adjust:
```python
import pytest

from speleoconvert.cli import main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "speleoconvert" in capsys.readouterr().out


def test_no_args_is_usage_error():
    assert main([]) == 2
```

- [ ] **Step 4: Run tests** — `uv run pytest -q`, all pass

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: convert CLI with strict mode, report output, exit codes"
```

---

### Task 10: `.plt` reader + geometry verification helper

Compass `.plt` files contain Compass's OWN computed station positions — comparing against them proves we *interpret* fields the way Compass does (declination, feet/degrees storage), not just tokenize them.

**Files:**
- Create: `src/speleoconvert/compass/plt.py`, `src/speleoconvert/verify.py`, `tests/test_verify.py`

**Interfaces:**
- `parse_plt(path) -> dict[str, tuple[float, float, float]]` — station name → (north_ft, east_ft, vert_ft). PLT lines: `M`/`D` commands `M <north> <east> <vert> S<station> ...`; ignore all other line types.
- `compute_positions(project: CompassProject) -> dict[str, tuple[float, float, float]]` — pure-python forward computation, seeded at (0,0,0) from the first station (or each fixed station converted to feet offsets from the first), applying declination: `true_bearing = bearing + declination`; `north += L*cos(inc)*cos(rad(tb))`, `east += L*cos(inc)*sin(rad(tb))`, `vert += L*sin(inc)`; skips `exclude_all` shots... **No — include all shots; Compass plots excluded-from-length shots too. Only skip nothing; note `no_adjust`/loops make `.plt` differ (Compass closes loops), so verification compares only projects/stations reachable without closed loops, or uses tolerance.**
- `compare(project, plt_stations) -> dict` with `max_err_ft`, `p95_err_ft`, `n` — relative to the first common station (subtract its coords in both frames before comparing).

- [ ] **Step 1: Write the failing test**

`tests/test_verify.py`:
```python
import math

from speleoconvert.compass.plt import parse_plt
from speleoconvert.verify import compare, compute_positions

from tests.test_mapping import _project, _shot  # reuse builders

PLT = (
    "Z -100 100 -100 100 -50 0\r\n"
    "NX D 1 1 1 C\r\n"
    "M 0.0 0.0 0.0 SE P -9 -9 -9 -9 I 0.0\r\n"
    "D 0.0 10.0 0.0 SS1 P 1 1 1 1 I 10.0\r\n"
)


def test_parse_plt(tmp_path):
    p = tmp_path / "x.plt"
    p.write_bytes(PLT.encode("cp437"))
    st = parse_plt(p)
    assert st["E"] == (0.0, 0.0, 0.0)
    assert st["S1"] == (0.0, 10.0, 0.0)


def test_compute_positions_east_shot():
    # bearing 90 + declination -6.13 => true bearing 83.87
    prj = _project([_shot("E", "S1", length=10.0, bearing=90.0, inc=0.0)])
    pos = compute_positions(prj)
    tb = math.radians(90.0 - 6.13)
    assert pos["S1"][0] == round(10.0 * math.cos(tb), 6)  # north
    assert pos["S1"][1] == round(10.0 * math.sin(tb), 6)  # east


def test_compare_zero_error_against_self(tmp_path):
    prj = _project([_shot("E", "S1", length=10.0, bearing=90.0, inc=0.0)])
    pos = compute_positions(prj)
    stats = compare(prj, pos)
    assert stats["max_err_ft"] == 0.0 and stats["n"] == 2
```

- [ ] **Step 2: Run to verify failure** — FAIL, modules missing

- [ ] **Step 3: Implement**

`src/speleoconvert/compass/plt.py`:
```python
"""Minimal Compass .plt reader — verification only (station positions)."""
from __future__ import annotations

from pathlib import Path


def parse_plt(path: str | Path) -> dict[str, tuple[float, float, float]]:
    stations: dict[str, tuple[float, float, float]] = {}
    text = Path(path).read_bytes().decode("cp437", errors="replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] in ("M", "D"):
            try:
                north, east, vert = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                continue
            for tok in parts[4:]:
                if tok.startswith("S") and len(tok) > 1:
                    stations.setdefault(tok[1:], (north, east, vert))
                    break
    return stations
```

`src/speleoconvert/verify.py`:
```python
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
```

- [ ] **Step 4: Run tests** — `uv run pytest -q`, all pass

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: plt reader + geometry verification helpers"
```

---

### Task 11: Corpus acceptance tests

**Files:**
- Create: `tests/test_corpus.py`

**Interfaces:**
- Consumes: everything. Env var `SPELEOCONVERT_CORPUS` → path of `cave survey/` sample tree.

- [ ] **Step 1: Write the test**

`tests/test_corpus.py`:
```python
"""Acceptance tests against the real (uncommitted) Compass corpus.

Run: SPELEOCONVERT_CORPUS="$HOME/.claude/jobs/3f4f5047/tmp/samples/cave survey" uv run pytest tests/test_corpus.py -v
"""
import os
from pathlib import Path

import pytest

from speleoconvert.ariane_writer import read_tml, write_tml
from speleoconvert.compass.parser_mak import load_project
from speleoconvert.compass.plt import parse_plt
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport
from speleoconvert.verify import compare

CORPUS = os.environ.get("SPELEOCONVERT_CORPUS")
pytestmark = pytest.mark.skipif(not CORPUS, reason="SPELEOCONVERT_CORPUS not set")


def _maks() -> list[Path]:
    if not CORPUS:
        return []
    return sorted(Path(CORPUS).rglob("*.mak")) + sorted(Path(CORPUS).rglob("*.MAK"))


@pytest.mark.parametrize("mak", _maks(), ids=lambda p: p.parent.name + "/" + p.name)
def test_convert_lenient_and_reread(mak: Path, tmp_path: Path):
    project = load_project(mak)
    report = ConversionReport(str(mak), "out.tml")
    survey_dict = map_project(project, strict=False, report=report)
    out = tmp_path / "out.tml"
    write_tml(survey_dict, out)
    back = read_tml(out)
    n_in = sum(len(s.shots) for d in project.dat_files for s in d.surveys)
    n_out = sum(
        len([sh for sh in sec.shots if sh.shot_type != "START"])
        for sec in back.sections
    )
    assert n_out == n_in, "every Compass shot must appear in the TML"


@pytest.mark.parametrize("mak", _maks(), ids=lambda p: p.parent.name + "/" + p.name)
def test_geometry_vs_plt(mak: Path):
    plt_path = None
    for cand in mak.parent.iterdir():
        if cand.suffix.lower() == ".plt" and cand.stem.lower() == mak.stem.lower():
            plt_path = cand
    if plt_path is None:
        pytest.skip("no matching .plt")
    project = load_project(mak)
    stats = compare(project, parse_plt(plt_path))
    if stats["n"] < 2:
        pytest.skip("no common stations")
    # Compass may close loops in .plt; allow slack, but catastrophic
    # misinterpretation (units, declination) would blow far past this.
    assert stats["p95_err_ft"] < 25.0, stats
```

- [ ] **Step 2: Run against corpus**

Run: `SPELEOCONVERT_CORPUS="$HOME/.claude/jobs/3f4f5047/tmp/samples/cave survey" uv run pytest tests/test_corpus.py -v 2>&1 | tail -40`

Expected: this WILL surface real-world quirks (odd headers, stray lines, extra directives). For each failure: diagnose, fix the parser/mapping with a new targeted unit test in the relevant test file (never loosen an assertion just to pass), re-run. Iterate until all projects pass or a specific file is genuinely malformed — document any such file in the report and skip-list it explicitly by name in the test with the reason string.

- [ ] **Step 3: Run the FULL suite** — `uv run pytest -q` (with env var), all pass

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test: corpus acceptance tests (conversion + geometry vs plt)"
```

---

### Task 12: Strict-mode corpus survey + README

**Files:**
- Create: `README.md`
- Create: `tools/corpus_report.py`

**Interfaces:**
- `tools/corpus_report.py` — walks `$SPELEOCONVERT_CORPUS`, converts every `.mak` in BOTH modes, prints a table: project, surveys, shots, strict OK/violation-categories, lenient report counts. Prints progress incrementally (one line per project as processed).

- [ ] **Step 1: Write `tools/corpus_report.py`**

```python
"""Survey the corpus: strict-mode readiness of every project.

Usage: SPELEOCONVERT_CORPUS=... uv run python tools/corpus_report.py
"""
import os
import sys
from pathlib import Path

from speleoconvert.compass.model import ParseError
from speleoconvert.compass.parser_mak import load_project
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport, StrictModeError

corpus = os.environ.get("SPELEOCONVERT_CORPUS")
if not corpus:
    sys.exit("set SPELEOCONVERT_CORPUS")

maks = sorted(Path(corpus).rglob("*.mak")) + sorted(Path(corpus).rglob("*.MAK"))
for i, mak in enumerate(maks, 1):
    label = f"[{i}/{len(maks)}] {mak.parent.name}/{mak.name}"
    try:
        project = load_project(mak)
        n_shots = sum(len(s.shots) for d in project.dat_files for s in d.surveys)
        report = ConversionReport(str(mak), "-")
        try:
            map_project(project, strict=True, report=report)
            status = "STRICT-OK"
        except StrictModeError as e:
            cats = sorted({en.category for en in e.entries})
            status = f"strict-violations: {','.join(cats)}"
        print(f"{label}: {n_shots} shots, {status}")
    except (ParseError, Exception) as e:  # noqa: BLE001 - survey tool, keep going
        print(f"{label}: FAILED - {e}")
```

- [ ] **Step 2: Run it and record results**

Run: `SPELEOCONVERT_CORPUS="$HOME/.claude/jobs/3f4f5047/tmp/samples/cave survey" uv run python tools/corpus_report.py`
Expected: one line per project, no `FAILED` lines (or documented exceptions).

- [ ] **Step 3: Write `README.md`**

```markdown
# speleoconvert

Lossless converter from [Fountainware Compass](https://www.fountainware.com/compass/)
cave survey projects to [Ariane's Line](https://arianesline.com/) `.tml`.

## Install / run

    uv tool install speleoconvert       # or: uv run speleoconvert ...
    speleoconvert convert "My Cave.mak"           # -> "My Cave.tml" + report
    speleoconvert convert "My Cave.mak" --strict  # error on any non-native field

## What "lossless" means

Every Compass field either maps to a native Ariane field, or (lenient mode) is
appended to the corresponding TML comment AND listed in `<out>.tml.report.json`.
`--strict` refuses to convert instead. Nothing is ever silently dropped.
See `docs/superpowers/specs/2026-07-25-compass-to-ariane-design.md` for the full
field mapping table.

## Verification

- Unit tests: `uv run pytest`
- Real-project acceptance + geometry-vs-`.plt` checks:
  `SPELEOCONVERT_CORPUS=/path/to/projects uv run pytest tests/test_corpus.py -v`
- Corpus survey: `SPELEOCONVERT_CORPUS=... uv run python tools/corpus_report.py`
- Final ground truth: open the converted `.tml` in Ariane's Line.

Real survey data is never committed to this repo (cave locations are sensitive).
```

- [ ] **Step 4: Full suite + lint**

Run: `uv run ruff check . && SPELEOCONVERT_CORPUS="$HOME/.claude/jobs/3f4f5047/tmp/samples/cave survey" uv run pytest -q`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "docs: README + corpus survey tool"
```

---

## Final acceptance (manual, user-in-the-loop)

1. Convert flagship projects: `speleoconvert convert ".../Peacock/01_Peacock Complete - Master Project File.MAK"` and MBSP.
2. Send the `.tml`s to the user to open in Ariane's Line (geometry, sections, comments, geo-location all present).
3. User verdict is the ship gate for v1.

## Self-review notes

- Spec coverage: input scope (Task 5 loader), strict/lenient (Tasks 7-9), comments+report (7, 8), geodesy incl. per-link datum (5, 6), feet-native units (8: `unit: FT`), depth computation (8), loop closure (8: CLOSURE shots), `.plt` verification (10, 11), corpus + never-commit rule (11), openspeleo re-read (9, 11), CLI exit codes (9), README (12). Web front-end and SpeleoDB upload: explicitly future phases per spec — no tasks.
- Type consistency: `map_project(project, *, strict, report)` used identically in Tasks 8, 9, 11, 12; `write_tml(dict, Path)`/`read_tml(Path)` in 2, 9, 11; `FormatSpec.parse(raw, file=, line_no=)` in 3, 4; `load_project` in 5, 9, 11, 12.
- Known risk consciously accepted: Ariane CLOSURE/START semantics are pinned by re-read tests, and the final Ariane-opens-it check is the ground truth; `test_simple.tml` in the read-only SpeleoDB repo can be consulted read-only if CLOSURE rendering looks wrong in Ariane.
