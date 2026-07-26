"""Every .tml we write must conform to the de-facto Ariane format (derived
from an Ariane-generated structural dump + Ariane-authored sample files, since
Ariane publishes no spec). See src/speleoconvert/conformance.py."""
import json
import os
from pathlib import Path

import pytest

from speleoconvert.ariane_writer import write_tml
from speleoconvert.compass.model import FixedStation, ShotFlags
from speleoconvert.compass.parser_mak import load_project
from speleoconvert.conformance import (
    CANONICAL_SHOT_FIELDS,
    CANONICAL_TOP_LEVEL,
    validate_tml,
)
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport
from tests.test_mapping import _project, _shot

FIXTURE = Path(__file__).parent / "fixtures" / "ariane_canonical.json"


def test_canonical_constants_match_vendored_dump():
    data = json.loads(FIXTURE.read_text())
    assert set(data) == CANONICAL_TOP_LEVEL
    shot = data["Data"]["SurveyData"][0]
    assert set(shot) == CANONICAL_SHOT_FIELDS


def test_kitchen_sink_output_conforms(tmp_path):
    fixed = [FixedStation("E", "f", 933560.866, 11070112.205, 0.0, raw="")]
    shots = [
        _shot("E", "S1", length=100.0, bearing=90.0, inc=-30.0, left_ft=None,
              comment="silty & tight"),
        _shot("S1", "S2", flags=ShotFlags(exclude_all=True, raw="X")),
        _shot("S2", "S3", azm2_deg=272.0, inc2_deg=0.0),
        _shot("S3", "E"),  # loop
    ]
    prj = _project(shots, fixed=fixed)
    object.__setattr__(prj.dat_files[0].surveys[0], "team", ("A & B", "C"))
    d = map_project(prj, report=ConversionReport("s", "o"))
    out = tmp_path / "out.tml"
    write_tml(d, out)
    assert validate_tml(out) == []


@pytest.mark.skipif(not os.environ.get("SPELEOCONVERT_CORPUS"),
                    reason="SPELEOCONVERT_CORPUS not set")
def test_all_corpus_conversions_conform(tmp_path):
    corpus = Path(os.environ["SPELEOCONVERT_CORPUS"])
    from tests.test_corpus import KNOWN_BROKEN
    maks = sorted(
        p for p in corpus.rglob("*")
        if p.suffix.lower() == ".mak" and p.name not in KNOWN_BROKEN
    )
    assert maks
    all_issues: list[str] = []
    for mak in maks:
        d = map_project(load_project(mak), report=ConversionReport("s", "o"))
        out = tmp_path / (mak.stem + ".tml")
        write_tml(d, out)
        issues = validate_tml(out)
        all_issues += [f"{mak.parent.name}/{mak.name}: {i}" for i in issues]
    assert all_issues == [], "\n".join(all_issues[:40])
