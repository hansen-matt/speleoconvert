# speleoconvert

Lossless converter from [Fountainware Compass](https://www.fountainware.com/compass/)
cave survey projects to [Ariane's Line](https://arianesline.com/) `.tml`.

## Install / run

    uv tool install speleoconvert       # or from a checkout: uv run speleoconvert ...
    speleoconvert convert "My Cave.mak"           # -> "My Cave.tml" + report
    speleoconvert convert "My Cave.mak" --strict  # error on any non-native field

Input is a whole Compass project: the `.mak` file plus the `.dat` survey files it
links. Output is one `.tml` (Ariane) plus `<out>.tml.report.json`, a field-level
audit of the conversion.

## What "lossless" means

Every Compass field either maps to a native Ariane field, or (lenient mode, the
default) is appended to the corresponding TML comment AND listed in the report.
`--strict` refuses to convert instead. Nothing is ever silently dropped.

| Compass | Ariane TML |
|---|---|
| project (`.mak`) | one `Survey` / one `.tml` (unit = feet, as stored by Compass) |
| survey | `Section` (name, date, surveyors, declination, corrections, format string) |
| shot | `Shot` (length, azimuth, inclination, LRUD, comment; depth computed from the traverse) |
| fixed stations (UTM + NAD27/NAD83/WGS84) | WGS84 lat/lon on the anchor shot (pyproj datum shift) |
| flag `X` (exclude) | `excluded` |
| backsights | averaged into azimuth/inclination (as Compass does at compile time); convention auto-detected per survey; raw readings kept in the shot comment + report |
| flags `L`/`P`/`C`, discovery date | shot/section comment + report (or `--strict` error) |
| missing LRUD (`-9.9`) | stays absent (`<Left/>`), counted in report |

See `docs/superpowers/specs/2026-07-25-compass-to-ariane-design.md` for the full
design and mapping rules.

## Verification

Every conversion **self-audits**: the written `.tml` is independently re-read
(stdlib XML, no shared code with the writer) and reconciled shot-by-shot
against the parsed Compass source — station names, lengths, azimuths,
inclinations, LRUD, depths, comments, flags, dates, team, and totals. Any
discrepancy fails the conversion with a nonzero exit code.

- Unit tests: `uv run pytest`
- Real-project acceptance + geometry-vs-`.plt` checks:
  `SPELEOCONVERT_CORPUS=/path/to/projects uv run pytest tests/test_corpus.py -v`
- Corpus survey (strict-readiness of every project):
  `SPELEOCONVERT_CORPUS=... uv run python tools/corpus_report.py`
- Final ground truth: open the converted `.tml` in Ariane's Line.

Real survey data is never committed to this repo (cave locations are sensitive).
