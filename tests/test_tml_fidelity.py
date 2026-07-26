"""End-to-end fidelity tests: what actually survives a TML write + re-read.

Documents hard limits of the Ariane TML format discovered 2026-07-26:
- the XML has NO fields for section declination, instrument corrections, the
  Compass format string, or section comments (Ariane derives declination from
  each section's date + the survey's location; useMagneticAzimuth=true);
- Ariane's data table renders the Section and Explorer fields as PLAIN TEXT,
  so embedded-XML conventions show up raw and must not be used.
Survey-level notes therefore ride the section's first shot comment; audit
metadata lives in the conversion report only.
"""
import zipfile
from pathlib import Path

import pytest

from speleoconvert.ariane_writer import read_tml, write_tml
from speleoconvert.compass.model import FixedStation, ShotFlags
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport
from tests.test_mapping import _project, _shot


def _convert(prj, tmp_path: Path, report=None) -> Path:
    d = map_project(prj, report=report or ConversionReport("s", "o"))
    out = tmp_path / "out.tml"
    write_tml(d, out)
    return out


def _xml(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("Data.xml").decode()


def test_tml_cannot_store_declination_natively(tmp_path):
    # Upstream behavior pin: if this ever starts passing declination through,
    # revisit the report-only handling.
    back = read_tml(_convert(_project([_shot("E", "S1")]), tmp_path))
    assert back.sections[0].declination == 0.0  # -6.13 was dropped by the format


def test_declination_and_corrections_reported(tmp_path):
    r = ConversionReport("s", "o")
    _convert(_project([_shot("E", "S1")], corrections=(1.0, 2.0, 3.0)),
             tmp_path, report=r)
    cats = {e.category for e in r.entries}
    assert "survey-declination" in cats
    assert "survey-corrections" in cats
    assert "survey-format" in cats


def test_section_and_explorer_fields_are_plain_text(tmp_path):
    # Ariane's data table displays these fields RAW (screenshot-verified even
    # for Ariane-authored files with embedded fragments), so plain text is the
    # only clean-rendering form — and it is itself genuine Ariane output
    # (test_simple.tml stores a bare string).
    xml = _xml(_convert(_project([_shot("E", "S1")]), tmp_path))
    assert "<Section>A</Section>" in xml            # plain name, no embedding
    assert "SectionDescription" not in xml
    assert "<Explorer>Matt</Explorer>" in xml       # plain names, no tags
    assert "&lt;Surveyor&gt;" not in xml
    assert "XMLExplorer" not in xml
    assert "XMLSurveyor" not in xml


def test_survey_comment_rides_first_shot(tmp_path):
    back = read_tml(
        _convert(_project([_shot("E", "S1")], comment="hi"), tmp_path)
    )
    first = back.sections[0].shots[0]
    assert "Survey comment: hi" in first.comment


def test_depths_round_to_half_foot(tmp_path):
    # 100 ft at -33 deg -> 54.4636 ft of depth -> 54.5
    shots = [_shot("E", "S1", length=100.0, bearing=90.0, inc=-33.0)]
    back = read_tml(_convert(_project(shots), tmp_path))
    s1 = [s for s in back.sections[0].shots if s.name == "S1"][0]
    assert s1.depth == 54.5
    assert s1.depth * 2 == int(s1.depth * 2)


def test_no_reversal_comments(tmp_path):
    # chain surveyed toward its fixed tie-in gets reversed silently
    fixed = [FixedStation("A", "f", 933560.866, 11070112.205, 0.0, raw="")]
    shots = [_shot("S1", "S2"), _shot("S2", "A")]
    back = read_tml(_convert(_project(shots, fixed=fixed), tmp_path))
    for sec in back.sections:
        for sh in sec.shots:
            assert "Reversed" not in (sh.comment or "")


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
    back = read_tml(_convert(_project(shots, fixed=fixed), tmp_path))
    sec = back.sections[0]
    by_name = {s.name: s for s in sec.shots}

    assert sec.date.isoformat() == "2024-02-23"
    start = sec.shots[0]  # the loop shot is also named "E"; take the START
    assert start.shot_type.value == "START"
    assert start.latitude == pytest.approx(30.48, abs=0.05)
    s1 = by_name["S1"]
    assert s1.length == 100.0 and s1.inclination == -30.0
    assert s1.left is None and s1.up == 2.0
    assert "silty restriction" in s1.comment
    assert by_name["S2"].excluded is True
    assert "azm2=272.0" in by_name["S3"].comment
    # team names present somewhere Ariane shows them
    team_text = " ".join((sec.surveyors or []) + (sec.explorers or []))
    assert "Matt" in team_text
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


def test_ampersand_names_escaped_once(tmp_path):
    prj = _project([_shot("E", "S1")])
    object.__setattr__(prj.dat_files[0].surveys[0], "team",
                       ("A. Pitkin & C. Roberson",))
    out = _convert(prj, tmp_path)
    xml = _xml(out)
    assert "<Explorer>A. Pitkin &amp; C. Roberson</Explorer>" in xml
    assert "&amp;amp;" not in xml
    # and it parses back to the plain name
    back = read_tml(out)
    sec = back.sections[0]
    team_text = " ".join((sec.surveyors or []) + (sec.explorers or []))
    assert "A. Pitkin & C. Roberson" in team_text
