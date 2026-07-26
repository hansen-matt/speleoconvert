"""End-to-end fidelity tests: what actually survives a TML write + re-read.

Documents a hard limit of the Ariane TML format discovered 2026-07-26: the XML
has NO fields for section declination, instrument corrections, or the Compass
format string — openspeleo-lib's Section model carries them, but ariane_encode
drops them at write time. Ariane instead derives declination from each
section's date + the survey's geographic location (useMagneticAzimuth=true).
Consequently speleoconvert must embed these values in the section comment.
"""
from pathlib import Path

import pytest

from speleoconvert.ariane_writer import read_tml, write_tml
from speleoconvert.compass.model import FixedStation, ShotFlags
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport
from tests.test_mapping import _project, _shot


def _convert_and_reread(prj, tmp_path: Path, report=None):
    d = map_project(prj, report=report or ConversionReport("s", "o"))
    out = tmp_path / "out.tml"
    write_tml(d, out)
    return read_tml(out)


def test_tml_cannot_store_declination_natively(tmp_path):
    # Upstream behavior pin: if this ever starts passing declination through,
    # the comment-embedding workaround can be removed.
    back = _convert_and_reread(_project([_shot("E", "S1")]), tmp_path)
    assert back.sections[0].declination == 0.0  # -6.13 was dropped by the format


def test_declination_preserved_in_section_description(tmp_path):
    r = ConversionReport("s", "o")
    back = _convert_and_reread(_project([_shot("E", "S1")]), tmp_path, report=r)
    sec = back.sections[0]
    assert "declination -6.13" in (sec.description or "")
    assert any(e.category == "survey-declination" for e in r.entries)


def test_nonzero_corrections_preserved_and_flagged(tmp_path):
    r = ConversionReport("s", "o")
    back = _convert_and_reread(
        _project([_shot("E", "S1")], corrections=(1.0, 2.0, 3.0)),
        tmp_path, report=r,
    )
    assert "corrections 1.0 2.0 3.0" in (back.sections[0].description or "")
    assert any(e.category == "survey-corrections" for e in r.entries)


def test_kitchen_sink_survives_roundtrip(tmp_path):
    fixed = [FixedStation("E", "f", 933560.866, 11070112.205, 0.0, raw="")]
    shots = [
        _shot("E", "S1", length=100.0, bearing=90.0, inc=-30.0,
              left_ft=None, up_ft=2.0, down_ft=3.0, right_ft=4.0,
              comment="silty restriction"),
        _shot("S1", "S2", flags=ShotFlags(exclude_all=True, raw="X")),
        _shot("S2", "S3", azm2_deg=272.0, inc2_deg=0.0),
        _shot("S3", "E"),  # loop
    ]
    back = _convert_and_reread(_project(shots, fixed=fixed), tmp_path)
    sec = back.sections[0]
    by_name = {s.name: s for s in sec.shots}

    assert sec.date.isoformat() == "2024-02-23"
    assert sec.surveyors == ["Matt"]
    start = sec.shots[0]  # the loop shot is also named "E"; take the START
    assert start.shot_type.value == "START"
    assert start.latitude == pytest.approx(30.48, abs=0.05)
    s1 = by_name["S1"]
    assert s1.length == 100.0 and s1.inclination == -30.0
    assert s1.left is None and s1.up == 2.0
    assert "silty restriction" in s1.comment
    assert by_name["S2"].excluded is True
    assert "azm2=272.0" in by_name["S3"].comment
    # the loop shot back onto E: REAL, solid, closure reference intact
    loop = [s for s in sec.shots if s.closure_to_id != -1]
    assert len(loop) == 1 and loop[0].shot_type.value == "REAL"
    # every input shot present
    assert len([s for s in sec.shots if s.shot_type.value != "START"]) == 4


def test_zero_declination_with_real_date_is_flagged():
    # DECLINATION 0.00 + a real date means Compass applied no correction but
    # Ariane WILL auto-compute one -> renderings will differ; migration should
    # know about it.
    prj = _project([_shot("E", "S1")])
    object.__setattr__(prj.dat_files[0].surveys[0], "declination_deg", 0.0)
    r = ConversionReport("s", "o")
    map_project(prj, report=r)
    assert any(e.category == "declination-zero" for e in r.entries)
