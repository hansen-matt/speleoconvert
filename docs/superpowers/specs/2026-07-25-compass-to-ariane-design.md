# speleoconvert — Compass → Ariane's Line converter

**Date:** 2026-07-25
**Status:** Approved design (pending user spec review)

## Purpose

Fountainware Compass has been the standard cave-survey program for decades; its sole
maintainer is over 80 and the community is migrating. Ariane's Line is the chosen
successor. `speleoconvert` converts entire Compass projects to Ariane's Line format
**with no loss of data**, so decades of survey archives can migrate with confidence.

## Scope

- **Input:** a whole Compass project — a `.mak` project file plus the one-or-more
  `.dat` survey files it references. (Bare `.dat` input is out of scope for v1.)
- **Output:** one Ariane `.tml` file per Compass project, plus a conversion report.
- **Non-goals (v1):** `.plt`/`.clp` conversion (derived data — Ariane recomputes),
  Ariane→Compass reverse conversion, SpeleoDB upload (future; speleomap repo shows how).

## Users & delivery

Two audiences, layered:

1. **Library + CLI (core, built first):** Python ≥3.11 package, `uv`/pip installable.
   `speleoconvert convert <project.mak> [-o out.tml] [--strict] [--report out.json]`
2. **Web front-end (later phase):** zero-install browser page (Pyodide — survey data
   never leaves the machine). The core is architected so this is additive.

## Architecture

Approach chosen: **new Python package with `openspeleo-lib` as the TML engine**,
with a strict firewall so the Compass side has zero third-party dependencies.

```
speleoconvert/
  compass/            # PURE STDLIB — knows nothing about Ariane
    model.py          #   frozen dataclasses mirroring Compass semantics exactly
    parser_dat.py     #   .dat → CompassDatFile (surveys, shots, all fields, raw text kept)
    parser_mak.py     #   .mak → CompassProject (datum, UTM zone, file links, fixed stations)
  geodesy.py          # UTM+datum (NAD27/NAD83/WGS84) → WGS84 lat/lon, via pyproj
  mapping.py          # CompassProject → openspeleo_lib Survey. ONLY file importing openspeleo_lib
  report.py           # conversion audit: every source field → where it landed
  cli.py              # argparse CLI
```

Data flow: parse `.mak` → discover + parse each `.dat` → assemble `CompassProject`
→ geodesy resolves fixed stations to WGS84 → mapping builds one Ariane `Survey`
(each Compass survey = one Ariane Section) → `ArianeInterface.to_file()` writes
`.tml` → report written alongside.

**Firewall rationale:** if the future Pyodide build chokes on
pydantic/orjson (openspeleo-lib deps), we can swap in a small self-owned TML writer
without touching the parser or model. Verified: `openspeleo-lib` 0.0.18
`ArianeInterface` has both `from_file` and `to_file`; its models carry
Compass-shaped slots (`declination`, `correction`, `correction2`, `compass_format`,
LRUD, `excluded`, per-shot `latitude`/`longitude`).

## Compass format coverage (lossless core)

### `.dat`

- Multiple surveys per file, form-feed separated; DOS-era encoding (cp437, with
  fallback); Ctrl-Z EOF tolerated.
- Per survey: cave name, survey name, date + comment, team list, declination,
  `FORMAT` string, correction pairs (`CORRECTIONS`, `CORRECTIONS2`).
- The `FORMAT` string (e.g. `DDDWLRUDLAaDdNF`) is decoded **fully**: azimuth /
  length / LRUD units, shot-item order, backsight presence (`B`), LRUD station
  association. Unknown format codes are a hard error in every mode — never guessed.
- Shots: from/to station, length, bearing, inclination, LRUD, optional backsight
  bearing/inclination, flags `#|…#` (`L` exclude-from-length, `P` exclude-from-plot,
  `X` exclude-totally, `C` no-adjust/closure), free-text comment.
- Missing-value sentinels (`-9.9`, `-999.25` family) parse to `None` ("absent"),
  never zero.
- Malformed lines are hard errors with `file:line` context.

### `.mak`

- Base location line (`@x,y,z,zone,convergence;`), datum (`&…;`), UTM zone (`$…;`),
  parameter flags (`!…;`), per-`.dat` file links (`#file.DAT, station[f,x,y,z];`)
  with fixed stations (unit flag `f`/`m` per station honored).
- `.dat` paths resolved case-insensitively relative to the `.mak` (files came from
  Windows; the corpus has case mismatches).

## Mapping to Ariane TML

| Compass | Ariane TML | Notes |
|---|---|---|
| project (`.mak`) | one `Survey` / one `.tml` | name from `.mak` filename |
| survey (in `.dat`) | `Section` | name, date, comment |
| declination, corrections | `Section.declination`, `.correction`, `.correction2` | carried, **never applied** — raw stays raw |
| format string | `Section.compass_format` | TML has this field natively |
| team | `Section.surveyors` / `explorers` | |
| shot from/to/length/bearing/inc | `Shot` fields | 1:1 |
| LRUD | `Shot.left/right/up/down` | Absent (`-9.9` sentinel) → `None`, which serializes as an empty TML element (`<Left/>`) and round-trips as absent (verified against openspeleo-lib 0.0.18). Occurrences counted in the report; never a strict-mode error. |
| flag `X` | `Shot.excluded` | native |
| flags `L`, `P`, `C` | comment + report (lenient) / error (strict) | no native slot |
| backsights | averaged into `Shot.azimuth`/`inclination` (Compass-compile equivalent); raw readings preserved in comment + report | convention (raw vs pre-corrected) detected empirically per survey from the median fore/back angular difference; fore/back disagreements > 5° reported (`backsight-discrepancy`); missing foresight recovered from backsight |
| fixed stations | `Shot.latitude/longitude` + survey `GeoLocation`, start elevation | after datum shift |
| lengths in feet | `unit = FT` | TML supports feet natively — **no unit conversion** |

**Depth:** Ariane's `Shot.depth` is required (diving-first tool). Depth is computed
deterministically — cumulative `length × sin(inclination)` walking the shot graph
from each fixed/entrance station. Inclination is *also* stored natively, so this
adds data rather than transforming it. The mapper therefore performs an ordered
traversal of the shot graph; disconnected components without a fixed station start
at relative 0 and are flagged in the report.

**Loop closure:** Compass adjusts at compile time; Ariane closes loops itself.
Raw shots pass through unadjusted. `.plt` (adjusted output) is used only for
verification, never as a source.

## Unmappable-data policy (two modes)

- **`--strict` (development default):** any field with no native Ariane slot is a
  hard error. Prevents silent semantic drift while building.
- **Lenient (migration default):** unmappable data is appended to the shot/section
  comment in the TML (travels with the data forever, visible in Ariane) **and**
  listed in a machine+human readable conversion report
  (`<output>.report.json` + summary text): every field, where it landed, per survey.
  Nothing is silently dropped in either mode.

## Geodesy

Fixed stations arrive as UTM eastings/northings (feet or meters per station flag)
in the `.mak` datum (corpus includes NAD27) and zone. `pyproj` performs
datum shift + projection to WGS84 lat/lon (Ariane's frame). The `.mak`
convergence value is carried into the report. `pyproj` is the only non-openspeleo
runtime dependency, and only `mapping.py`-side code touches it (behind the firewall).

## Error handling

- Parse errors: always fatal, with `file:line:column` and the offending text.
- Mapping gaps: per the two-mode policy above.
- Missing `.dat` referenced by `.mak`: fatal, names the missing file.
- Encoding anomalies: decoded via cp437; undecodable bytes are a parse error
  (never silently replaced).
- Exit codes: 0 success, 1 conversion error, 2 usage error — scriptable for batch
  migration runs.

## Testing

1. **Unit tests** on synthetic fixtures (committed to the repo): format-string
   permutations, backsights, flags, sentinels, multi-survey files, quirky `.mak`s.
2. **Corpus run:** ~25 real projects (Peacock 6 `.dat`s, OLeno 9, MBSP Regions,
   single-`.dat` caves…) under `~/Downloads/cave survey/`, referenced via env var
   `SPELEOCONVERT_CORPUS`. **Real survey data is never committed** (cave locations
   are sensitive). Every project must convert in strict mode or fail with an
   explained, user-accepted report entry.
3. **Geometry verification:** station positions computed from our parsed model
   (declination + corrections applied the Compass way) compared against Compass's
   own `.plt` output within tolerance — proves we *interpreted* fields correctly,
   not just tokenized them.
4. **Output validation:** every generated `.tml` is re-read with
   `openspeleo_lib.ArianeInterface.from_file` in tests.
5. **Acceptance:** user opens converted flagship projects (Peacock, MBSP) in a real
   Ariane's Line installation — the final ground truth.
6. CI-ready: `pytest`, `ruff`, `uv` project layout.

## Risks

- **Pyodide compatibility of pydantic/orjson/pyproj** — deferred to the web phase;
  the firewall keeps the escape hatch (own TML writer, JS-side geodesy) cheap.
- **`Shot.depth` semantics in Ariane** (absolute vs relative) — resolved during
  implementation against `fixtures/test_simple.tml` and the user's Ariane install.
- **Format-string variants** in decades-old files — mitigated by hard-error policy
  plus the breadth of the real corpus.

## References

- `openspeleo-lib` 0.0.18 (OpenSpeleo/pytool_openspeleo_lib) — TML read/write engine.
- SpeleoDB repo (read-only): `speleodb/processors/_impl/{ariane,compass}.py`,
  `fixtures/test_simple.tml`.
- speleomap repo (read-only): SpeleoDB API client patterns, for a future upload step.
- Compass file format documentation (Fountainware), user-supplied corpus.
