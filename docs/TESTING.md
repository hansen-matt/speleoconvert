# The speleoconvert test suite

The data this tool migrates cost thousands of dive hours. The suite is built
on one principle: **every guarantee is verified by an independent path, and
every verifier is itself tested for its ability to detect failure.** No layer
trusts the code it checks.

Run everything: `SPELEOCONVERT_CORPUS=/path/to/projects uv run pytest`
(without the env var, the real-data suites skip and the synthetic suites
still run — that's what CI without private data does).

## Layer 1 — Parsers (synthetic, byte-exact)

`test_parser_dat.py`, `test_parser_mak.py`, `test_parser_dat_quirks.py`,
`test_model.py`

Compass `.dat`/`.mak` parsing against hand-built files: FORMAT-string
decoding (every unit/order variant in the corpus), backsight columns,
`-9.9`/`-999.25` sentinels, flags, cp437/CRLF/form-feed structure, and the
real-world quirks that broke v1 (blank cave-name lines, optional datum/zone,
bare link stations, editor placeholder rows). Malformed input must hard-error
with `file:line` — never guess. Only the byte-exact placeholder template row
is ever skipped, and it is reported.

## Layer 2 — Semantics (mapping)

`test_mapping.py`, `test_mapping_connectivity.py`, `test_backsights.py`

Compass → Ariane translation rules: connectivity-ordered emission (forward
references must not create phantom anchor points), tail-tie chain reversal
(azimuth +180 / inclination negated), loop shots as REAL + `closure_to_id`,
backsight convention detection (raw vs pre-corrected, voted per survey) and
circular-mean averaging including the north-wraparound case, depth
propagation, fixed-station anchoring, and the strict-mode contract (what is a
violation, what is exempt and why — each exemption documented in
`report.py`).

## Layer 3 — Geodesy (measured, not assumed)

`test_geodesy.py`

UTM+datum → WGS84 against known coordinates, including the NAD27→WGS84 shift
being in the right ballpark (not zero, not wild) and feet-vs-meters station
flags. The decisive calibration was done against Compass's own KML exports of
real projects: all anchors within 0–2 ft, which also settled the
international-vs-US-survey-foot question empirically.

## Layer 4 — Format fidelity (what the TML can actually hold)

`test_ariane_writer.py`, `test_tml_fidelity.py`, `test_firewall.py`

Pins the writer-library behavior we depend on, and **documents the format's
hard limits as failing-by-design expectations**: TML has no fields for
declination, instrument corrections, the Compass format string, or section
comments — one test asserts the drop happens, so if a library upgrade ever
starts round-tripping these, we're told to remove our workarounds. Also: the
Ariane-native forms we must emit (plain Section names, plain-text Explorer,
`0xrrggbbaa` colors, absent-LRUD as empty elements), single-escaped
ampersands, and the kitchen-sink round-trip (every feature through
write→re-read at once). The firewall test enforces that only
`ariane_writer.py` touches the writer library.

## Layer 5 — Conformance (the de-facto spec)

`conformance.py`, `test_conformance.py`, `tests/fixtures/ariane_canonical.json`

Ariane publishes no spec, so one was derived: element names from a canonical
structural dump of an Ariane-generated file, value formats from
Ariane-authored samples (colors, lowercase booleans, enums, ISO dates,
lowercase units), plus global ID referential integrity. Every synthetic and
every corpus conversion must validate clean. This layer caught the color
format bug (`#FFB366` vs `0xrrggbbaa`) that five rounds of eyeballing in
Ariane had missed.

## Layer 6 — Reconciliation (the data-integrity backstop)

`reconcile.py`, `test_reconcile.py`

The written `.tml` is re-read with stdlib XML — deliberately sharing no code
with the writer — and every Compass shot must be found with every measurement
intact: names, exact length, azimuth/inclination up to the documented
transforms (circular comparison; raw data contains bearings like −91.0),
LRUD absent-vs-zero, depth deltas vs `length×sin(inc)`, comments verbatim,
flags, dates, team, and totals (count, summed length, station set). This runs
inside the CLI on **every real conversion**; discrepancies fail the run.

The auditor's detection power is itself proven: ten corruption classes are
deliberately injected into written files (altered length/azimuth/LRUD/depth,
dropped shot, deleted comment, flipped exclusion, erased team, broken
depth-chain continuity, stripped GPS anchor) and each must be caught. An auditor that passes everything is worthless; this one is tested
to fail.

## Layer 7 — Randomized end-to-end (fuzz)

`test_fuzz_roundtrip.py`

A generator writes genuine Compass `.DAT`/`.MAK` bytes — loops, branches,
shuffled shot order (forcing deferred emission and reversals), backsight
columns with realistic error, sentinels, flags, ampersands, 0°/360°
bearings — and the full pipeline must produce a conformant TML with *perfect*
reconciliation, for 12 seeds. This explores input combinations no hand-written
test anticipates.

## Layer 8 — The real corpus (ground truth at scale)

`test_corpus.py` (requires `SPELEOCONVERT_CORPUS`)

Per real project (~50 `.mak`s, ~18,000 shots): parse+convert+re-read with
shot-count parity; **geometry verification against Compass's own `.plt`
output** (our independently computed station positions must match Compass's,
extent-scaled tolerance — this is the check that proves we *interpret* fields
the way Compass does, and it anchors the feet/degrees storage assumption);
and full per-shot reconciliation. Genuinely broken source files and
`.plt`s that embed conflicting duplicate surveys are skip-listed by name with
the investigation results as the reason string — nothing is skipped silently.

The corpus itself is private (cave locations) and never committed.

## Layer 9 — Acceptance (a human in Ariane)

The final gate has been a human opening converted flagship projects in a
current Ariane's Line install and comparing against Compass renderings —
this caught the things only a UI can show (Null-Island fragments, dashed
closure rendering, raw-markup team fields, `.0` display noise), each of which
then became a permanent test in layers 4–6.
