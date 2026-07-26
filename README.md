# speleoconvert

Lossless converter from [Fountainware Compass](https://www.fountainware.com/compass/)
cave survey projects to [Ariane's Line](https://www.arianesline.com/) `.tml`.

Compass has been the standard cave survey program for decades; its lone
maintainer is in his 80s and the community is migrating. The survey data being
migrated represents thousands of hours of (often underwater) exploration, so
this tool's first design goal is that **nothing is lost or corrupted** — and
that this is *verified*, not assumed, on every single conversion.

## Quick start

    uv tool install speleoconvert          # or from a checkout: uv run speleoconvert ...
    speleoconvert convert "My Cave.mak"            # -> "My Cave.tml" + audit report
    speleoconvert convert "My Cave.mak" --strict   # refuse instead of embedding leftovers

Input is a whole Compass project: the `.mak` project file plus the `.dat`
survey files it links (resolved case-insensitively; DOS-era cp437 encoding
handled). Output is one Ariane `.tml` plus `<out>.tml.report.json`, a
field-level audit of every conversion decision.

Exit codes: `0` success (including the built-in reconciliation audit),
`1` conversion/verification failure, `2` usage error — safe for batch
migration scripts.

## What "lossless" means here

Every Compass field either maps to a native Ariane field, or is embedded in a
comment that travels with the data, or (for display-only metadata) is recorded
in the report. Nothing is silently dropped. `--strict` turns any non-native
mapping into a hard error instead.

| Compass | Ariane TML |
|---|---|
| project (`.mak`) | one `Survey` / one `.tml` (unit = feet, as Compass stores) |
| survey | `Section` (name, ISO date, team) |
| shot | `Shot`: length, azimuth, inclination, LRUD, comment; depth computed from the traverse (half-foot display rounding, full precision propagated) |
| fixed stations (UTM + NAD27/NAD83/WGS84) | WGS84 lat/lon on the anchor shot (pyproj datum shift; verified to 0–2 ft against Compass's own KML exports) |
| redundant backsights | averaged into azimuth/inclination exactly as Compass compiles them; raw-vs-corrected convention auto-detected per survey; raw readings preserved in the shot comment |
| loops | measured loop shot stays REAL (solid in Ariane) with `closure_to_id`; Ariane's loop compensation closes them |
| flag `X` (exclude) | `excluded` (Ariane draws dashed, skips in processing) |
| flags `L`/`P`/`C`, discovery dates, survey comments | shot comment + report (or `--strict` error) |
| missing LRUD (`-9.9` sentinel) | stays absent (`<Left/>`), never fake zeros |
| declination / instrument corrections / format string | report (TML has no fields for them; Ariane derives declination from section date + location) |

Chains surveyed *toward* their tie-in are reversed (azimuth +180°,
inclination negated — geometry-preserving, required by Ariane's rooted-tree
model) and noted in the report. Shots are emitted in connectivity order, not
file order, so surveys that reference stations defined in later files anchor
correctly.

## Built-in verification (every run)

After writing the `.tml`, the CLI **independently re-reads it** (stdlib XML,
no shared code with the writer) and reconciles it shot-by-shot against the
parsed Compass source: station names, exact lengths, azimuths/inclinations,
LRUD, depth deltas, comments, flags, dates, team members, and totals. Any
discrepancy fails the run — a corrupted output cannot exit 0.

See [docs/TESTING.md](docs/TESTING.md) for the full verification stack
(format conformance against Ariane-authored reference files, corruption-
detection tests, randomized fuzzing, real-corpus geometry checks against
Compass's own `.plt` output).

## Ariane compatibility notes

Ariane publishes no file spec; the output format is matched against files
authored by Ariane itself (see `tests/fixtures/ariane_canonical.json` and the
conformance suite). Where the `openspeleo-lib` writer deviates from
Ariane-native output (team-field encoding, `XMLExplorer`/`XMLSurveyor` tags,
CSS-style colors), the writer post-processes the XML to match; upstream fixes
proposed in [OpenSpeleo/pytool_openspeleo_lib#65](https://github.com/OpenSpeleo/pytool_openspeleo_lib/pull/65).

## Development

    uv run pytest                      # unit + integration tests
    SPELEOCONVERT_CORPUS=/path/to/projects uv run pytest   # + real-corpus suites
    SPELEOCONVERT_CORPUS=... uv run python tools/corpus_report.py  # strict-readiness survey
    uv run ruff check .

Layout: `src/speleoconvert/compass/` (pure-stdlib Compass parsers + model),
`mapping.py` (Compass → Ariane dict; the semantics live here),
`ariane_writer.py` (the **only** module that imports `openspeleo-lib`;
post-processes to Ariane-native XML), `geodesy.py` (pyproj), `reconcile.py`
(the self-audit), `conformance.py` (de-facto format validator), `report.py`,
`cli.py`. The firewall (writer-library imports confined to one file) is
enforced by a test, keeping a future browser/Pyodide build cheap.

Real survey data is never committed to this repo — cave locations are
sensitive. Tests that need it read `SPELEOCONVERT_CORPUS` and skip otherwise.

## Roadmap

- Web front-end (drag a zip, get a `.tml`) via Pyodide — the core is
  structured for it.
- Design history: `docs/superpowers/specs/` and `docs/superpowers/plans/`.
