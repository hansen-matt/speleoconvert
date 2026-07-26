# speleoconvert

Convert [Fountainware Compass](https://www.fountainware.com/compass/) cave
survey projects to [Ariane's Line](https://www.arianesline.com/) `.tml` —
**losslessly, and with the losslessness verified on every run**.

Compass has been the standard cave survey program for decades. Its sole
maintainer is in his 80s, and cave survey teams are migrating their archives
to Ariane's Line. Those archives represent thousands of hours of exploration,
much of it underwater cave diving that cannot simply be re-surveyed. This
tool exists so that migration loses nothing — and proves it, shot by shot,
every time it runs.

**Status:** production-ready CLI. Validated against ~50 real Compass projects
(~18,000 survey shots, single-cave files up to multi-file systems with loops,
fixed GPS stations, and 40 years of format quirks), with converted output
verified in a current Ariane's Line installation.

## Requirements

- Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/) (or plain pip)
- A Compass project: one `.mak` file plus the `.dat` files it references

## Install

    uv tool install git+https://github.com/hansen-matt/speleoconvert

or from a checkout:

    git clone https://github.com/hansen-matt/speleoconvert
    cd speleoconvert
    uv run speleoconvert --version

## Usage

    speleoconvert convert "My Cave.mak"

writes `My Cave.tml` (open it in Ariane) and `My Cave.tml.report.json`, a
field-level audit of every conversion decision, and prints a summary:

    speleoconvert report: My Cave.mak -> My Cave.tml
      backsight-averaged: 213
      shot-flags: 12
      ...
    reconciliation: OK (2299 shots verified against the source)
    wrote My Cave.tml

Options: `-o OUT.tml` (output path), `--report PATH`, `-q` (quiet),
`--strict` (refuse to convert if anything cannot map to a native Ariane
field, instead of embedding it in a comment).

Batch-convert an archive:

    find /archives -iname '*.mak' -exec speleoconvert convert {} \;

Exit codes: `0` success **including the built-in data audit**, `1` any
parse/conversion/verification failure, `2` usage error — a failed project
can't slip through a batch run silently. Files that are genuinely broken
(e.g. a `.mak` referencing a `.dat` that no longer exists, or corrupted
rows) fail with a `file:line` message telling you what to repair; the
converter never guesses.

## Opening the result in Ariane

- **Geometry and geo-referencing come across automatically**: shots stay in
  feet with magnetic azimuths; `.mak` fixed stations (NAD27/NAD83/WGS84 UTM)
  become WGS84 anchors, verified to within 0–2 ft of Compass's own KML
  exports.
- **Run loop compensation** (LOOPS panel). Compass silently distributed loop
  misclosure at compile time; Ariane shows raw loops until you compensate.
- **Dashed lines are excluded shots** — the faithful translation of Compass's
  `X` flag (Compass hid them entirely; Ariane draws them dashed and skips
  them in processing).
- **Declination:** the TML format has no declination field. Ariane computes
  it from each survey's date and the cave's location. Surveys recorded with
  `DECLINATION: 0.00` and a real date are flagged in the report
  (`declination-zero`), because Ariane will apply a correction Compass never
  did.

## What "lossless" means

Every Compass field either maps to a native Ariane field, travels in a
comment on the relevant shot, or (display-only metadata) is recorded in the
JSON report. Nothing is silently dropped. `--strict` turns any non-native
mapping into a hard error.

| Compass | becomes |
|---|---|
| project (`.mak` + `.dat`s) | one `.tml`; each Compass survey is an Ariane Section |
| shot: length / bearing / inclination / LRUD / comment | native Shot fields; depth computed from the traverse (displayed to the nearest half-foot; full precision propagated internally) |
| fixed stations (UTM + datum) | WGS84 lat/lon anchors |
| redundant backsights | averaged into azimuth/inclination exactly as Compass compiles them (raw-vs-corrected convention auto-detected per survey); raw readings preserved in the shot comment |
| loops | the measured loop shot stays a normal solid shot, machine-tagged with its closure target |
| flag `X` (exclude from processing) | Ariane `Excluded` |
| flags `L`/`P`/`C`, discovery dates, survey comments | shot comment + report |
| missing LRUD (`-9.9` sentinel) | stays absent — never fake zeros |
| declination, instrument corrections, format string | report (no TML fields exist for them) |
| survey team | Ariane Explorer field (plain names) |

Surveys recorded *toward* their tie-in point are reversed (azimuth +180°,
inclination negated — geometry-preserving; Ariane's data model is a rooted
tree). Shots are emitted in connectivity order, so surveys that start at
stations defined in later files anchor correctly.

## How you know nothing was lost

Every run self-audits: after writing the `.tml`, the CLI re-reads it with an
independent parser (Python stdlib XML — no code shared with the writer) and
reconciles it against the Compass source shot by shot: station names, exact
lengths, azimuths, inclinations, LRUD, depth deltas, comments, flags, dates,
team members, and totals. Any discrepancy fails the run.

The test suite behind that guarantee — including deliberate file-corruption
tests that prove the auditor catches tampering, randomized fuzz projects, and
geometry verification against Compass's own `.plt` output — is described in
[docs/TESTING.md](docs/TESTING.md).

## Known limitations

- Ariane's TML format cannot store per-survey declination or instrument
  corrections; they are preserved in the report only (see above for how
  Ariane handles declination itself).
- Redundant-backsight handling is fully tested synthetically, but no file in
  the validation corpus contains real backsight columns — review the report
  of the first real backsight archive you convert.
- Ariane's data table displays some stored fields verbatim (a quirk that
  applies equally to files Ariane writes itself).
- The Compass `.plt`/`.clp` files are not converted: they are compiled
  output, which Ariane regenerates from the raw data.

## Development

    uv run pytest                 # synthetic suites (no private data needed)
    SPELEOCONVERT_CORPUS=/path/to/projects uv run pytest   # + real-corpus suites
    uv run ruff check .

Layout: `src/speleoconvert/compass/` — pure-stdlib Compass parsers;
`mapping.py` — Compass→Ariane semantics; `ariane_writer.py` — the only module
that touches the TML-writing library ([openspeleo-lib](https://github.com/OpenSpeleo/pytool_openspeleo_lib),
from the OpenSpeleo/SpeleoDB project), plus post-processing that matches
Ariane-native output byte conventions; `geodesy.py` — datum shifts (pyproj);
`reconcile.py` — the per-run audit; `conformance.py` — validates output
against the de-facto Ariane format (derived from Ariane-authored files, since
no official spec exists). Upstream fixes for the writer library are proposed
in [OpenSpeleo/pytool_openspeleo_lib#65](https://github.com/OpenSpeleo/pytool_openspeleo_lib/pull/65).

No cave survey data is committed to this repository — cave locations are
sensitive. Tests that need real projects read the `SPELEOCONVERT_CORPUS`
environment variable and skip when it is unset.

## License

[AGPL-3.0](LICENSE), matching the `openspeleo-lib` dependency.
