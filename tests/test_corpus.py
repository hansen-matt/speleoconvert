"""Acceptance tests against the real (uncommitted) Compass corpus.

Run: SPELEOCONVERT_CORPUS="/path/to/cave survey" uv run pytest tests/test_corpus.py -v
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

# Projects that are genuinely broken on disk, with the reason.
KNOWN_BROKEN = {
    "M2 Blue Cave System Project.MAK":
        "references 'Fennells Funnel.DAT' which does not exist in the directory",
    "Indian data.mak":
        "Indian data.dat contains a placeholder shot row 'From Station  To Station'"
        " (spaces in station names; leftover import-template scratch data)",
    "Indian data for import.mak":
        "same placeholder shot row family as Indian data.mak (import scratch files)",
    "Indian Springs Cave.MAK":
        "links Indian data.dat, which has the placeholder shot row",
    "m2blueHires.mak":
        "references 'M2B.DAT' which does not exist (directory has M2BHires.DAT)",
}

# Projects whose .plt disagrees with the raw shot data for documented reasons
# (conflicting duplicate surveys, Compass conflict resolution / loop adjustment).
# Conversion is still exercised for these; only the .plt geometry tripwire is
# skipped. Verified by delta-cluster analysis: agreement for most stations,
# whole-subtree translations for the conflicted branches.
GEOMETRY_EXEMPT = {
    "M2 Blue Cave.MAK":
        "FF_S1..FF_S6 surveyed in both M2 Blue Cave.DAT and Fennels Swallett.DAT "
        "with ~3100 ft disagreement; plt shows Compass's conflict resolution",
    "Manatee.MAK":
        "two subtrees offset ~860 ft (duplicate-survey conflict); "
        "753/1095 stations agree within closure noise",
    "Rose Creek.MAK":
        "McCormick branch offset ~90 ft from plt (duplicate-survey conflict "
        "between Rose Creek and McCormick DATs)",
}


def _maks() -> list[Path]:
    if not CORPUS:
        return []
    return sorted(
        p for p in Path(CORPUS).rglob("*")
        if p.suffix.lower() == ".mak" and p.name not in KNOWN_BROKEN
    )


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
        len([sh for sh in sec.shots if sh.shot_type.value != "START"])
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
    if mak.name in GEOMETRY_EXEMPT:
        pytest.skip(GEOMETRY_EXEMPT[mak.name])
    project = load_project(mak)
    stats = compare(project, parse_plt(plt_path))
    if stats["n"] < 2:
        pytest.skip("no common stations")
    # This is a tripwire for catastrophic misinterpretation (axis swap, unit
    # or declination errors show up as whole-cave-scale offsets). The .plt has
    # Compass's loop-closure adjustment baked in (and may be stale relative to
    # the .DAT), so small percent-of-extent differences are expected.
    tolerance = max(50.0, 0.015 * stats["extent_ft"])
    assert stats["p95_err_ft"] < tolerance, stats
