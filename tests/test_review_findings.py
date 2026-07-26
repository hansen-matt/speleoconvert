"""Regression tests for the 2026-07-26 self-review findings — primarily the
data-integrity holes: -999 foresight sentinels averaged into output, secondary
GPS anchors silently dropped, and reconciler blind spots from shared code."""

import pytest

from speleoconvert.ariane_writer import write_tml
from speleoconvert.cli import main
from speleoconvert.compass.model import FixedStation, ParseError
from speleoconvert.compass.parser_dat import parse_dat_text
from speleoconvert.mapping import map_project
from speleoconvert.reconcile import reconcile
from speleoconvert.report import ConversionReport
from tests.test_mapping import _project, _shot

BS_HEADER = ("FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT     AZM2     INC2"
             "   FLAGS COMMENTS")


def _bs_dat(rows: list[str]) -> str:
    return (
        "cave\r\nSURVEY NAME: A\r\nSURVEY DATE: 2 23 2024  COMMENT:\r\n"
        "SURVEY TEAM: \r\nMatt\r\n"
        "DECLINATION: 0.00  FORMAT: DDDWLRUDLAaDdNF  CORRECTIONS: 0.00 0.00 0.00"
        "  CORRECTIONS2: 0.00 0.00\r\n\r\n" + BS_HEADER + "\r\n\r\n"
        + "\r\n".join(rows) + "\r\n"
    )


# --- finding 1 (critical): -999 foresight sentinels ------------------------

def test_missing_foresight_bearing_parses_to_none():
    dat = parse_dat_text(_bs_dat(
        ["A1 A2 10.00 -999.00 5.00 1.00 1.00 1.00 1.00 92.00 -5.20"]
    ), file="bs.dat")
    shot = dat.surveys[0].shots[0]
    assert shot.bearing_deg is None
    assert shot.azm2_deg == 92.0


def test_missing_foresight_inclination_parses_to_none():
    dat = parse_dat_text(_bs_dat(
        ["A1 A2 10.00 90.00 -999.00 1.00 1.00 1.00 1.00 271.00 12.00"]
    ), file="bs.dat")
    shot = dat.surveys[0].shots[0]
    assert shot.inclination_deg is None
    assert shot.inc2_deg == 12.0


def test_missing_foresight_derives_output_from_backsight(tmp_path):
    # end-to-end: bearing -999 with backsight 92 -> azimuth 272 (flipped),
    # never an averaged monstrosity; must reconcile cleanly
    dat = parse_dat_text(_bs_dat(
        ["A1 A2 10.00 -999.00 -999.00 1.00 1.00 1.00 1.00 92.00 -5.20",
         "A2 A3 20.00 45.00 0.00 1.00 1.00 1.00 1.00 226.00 0.00"]
    ), file="bs.dat")
    from speleoconvert.compass.model import (
        CompassDatFile,
        CompassProject,
        DatLink,
    )
    prj = CompassProject(
        mak_path="/tmp/bs.mak", base_easting_m=None, base_northing_m=None,
        base_elevation_m=None, base_zone=None, convergence_deg=None,
        datum="WGS 1984", flags_raw=None, comments=(),
        links=(DatLink("bs.dat", "WGS 1984", 17),),
        dat_files=(CompassDatFile("bs.dat", dat.surveys),),
    )
    d = map_project(prj, report=ConversionReport("s", "o"))
    out = tmp_path / "o.tml"
    write_tml(d, out)
    assert reconcile(prj, out) == []
    shots = {s["name"]: s for sec in d["sections"] for s in sec["shots"]}
    assert shots["A2"]["azimuth"] == pytest.approx(272.0)   # from backsight
    assert abs(shots["A2"]["inclination"]) == pytest.approx(5.2)


# --- finding 2 (major): secondary fixed anchors ------------------------------

def test_secondary_fixed_anchor_preserved(tmp_path):
    fixed = [
        FixedStation("E", "f", 933560.866, 11070112.205, 0.0, raw=""),
        FixedStation("S2", "f", 933660.866, 11070212.205, 0.0, raw=""),
    ]
    prj = _project([_shot("E", "S1"), _shot("S1", "S2")], fixed=fixed)
    r = ConversionReport("s", "o")
    d = map_project(prj, report=r)
    out = tmp_path / "o.tml"
    write_tml(d, out)
    shots = {s["name"]: s for sec in d["sections"] for s in sec["shots"]}
    assert "Compass fixed station S2: WGS84" in shots["S2"]["comment"]
    assert any(e.category == "fixed-station-secondary" for e in r.entries)
    assert reconcile(prj, out) == []


def test_reconcile_detects_dropped_secondary_anchor(tmp_path):
    # if the mapper ever regresses to dropping the coordinate, the auditor
    # must catch it: simulate by stripping the comment from the written file
    import re
    import zipfile
    fixed = [
        FixedStation("E", "f", 933560.866, 11070112.205, 0.0, raw=""),
        FixedStation("S2", "f", 933660.866, 11070212.205, 0.0, raw=""),
    ]
    prj = _project([_shot("E", "S1"), _shot("S1", "S2")], fixed=fixed)
    d = map_project(prj, report=ConversionReport("s", "o"))
    out = tmp_path / "o.tml"
    write_tml(d, out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("Data.xml").decode()
    xml = re.sub(r"<Comment>Compass fixed station[^<]*</Comment>", "<Comment/>",
                 xml)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("Data.xml", xml)
    assert any("fixed station 'S2'" in p for p in reconcile(prj, out))


# --- finding 4: empty surveys must not block a project -----------------------

def test_placeholder_only_survey_converts(tmp_path):
    empty = (
        "cave\r\nSURVEY NAME: EMPTY\r\nSURVEY DATE: 1 1 2020  COMMENT:template\r\n"
        "SURVEY TEAM: \r\n\r\n"
        "DECLINATION: 0.00  FORMAT: DDDDUDRLLADN\r\n\r\n"
        "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n\r\n"
        "        From Station           To Station     0.00     0.00     0.00"
        "     0.00     0.00     0.00     0.00\r\n"
    )
    real = (
        "cave\r\nSURVEY NAME: R\r\nSURVEY DATE: 1 2 2020  COMMENT:\r\n"
        "SURVEY TEAM: \r\nMatt\r\n"
        "DECLINATION: 0.00  FORMAT: DDDDUDRLLADN\r\n\r\n"
        "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n\r\n"
        "R1 R2 10.00 90.00 0.00 1.00 1.00 1.00 1.00\r\n"
    )
    (tmp_path / "p.dat").write_bytes((empty + "\x0c" + real).encode("cp437"))
    (tmp_path / "p.mak").write_bytes(
        "@284551.1,3373992.3,0.0,17,-1.14;\r\n&WGS 1984;\r\n$17;\r\n"
        "#p.dat;\r\n".encode("cp437"))
    assert main(["convert", str(tmp_path / "p.mak"), "-q"]) == 0


# --- findings 5-7: hard errors instead of crashes/corruption -----------------

def test_control_character_is_parse_error():
    bad = _bs_dat(["A1 A2 10.00 90.00 0.00 1.00 1.00 1.00 1.00 270.00 0.00"])
    bad = bad.replace("COMMENT:", "COMMENT:ding\x07dong")
    with pytest.raises(ParseError) as e:
        parse_dat_text(bad, file="q.dat")
    assert "control character" in str(e.value)


def test_negative_length_is_parse_error():
    with pytest.raises(ParseError) as e:
        parse_dat_text(_bs_dat(
            ["A1 A2 -10.00 90.00 0.00 1.00 1.00 1.00 1.00 270.00 0.00"]
        ), file="q.dat")
    assert "negative shot length" in str(e.value)


def test_negative_lrud_is_parse_error():
    with pytest.raises(ParseError) as e:
        parse_dat_text(_bs_dat(
            ["A1 A2 10.00 90.00 0.00 -5.00 1.00 1.00 1.00 270.00 0.00"]
        ), file="q.dat")
    assert "negative passage dimension" in str(e.value)


def test_bad_mak_zone_is_parse_error(tmp_path):
    (tmp_path / "b.mak").write_bytes(b"$16A;\r\n#x.dat;\r\n")
    from speleoconvert.compass.parser_mak import parse_mak
    with pytest.raises(ParseError) as e:
        parse_mak(tmp_path / "b.mak")
    assert "bad UTM zone" in str(e.value)


# --- finding 11: two-digit years ---------------------------------------------

def test_two_digit_years():
    from speleoconvert.mapping import _iso_date
    assert _iso_date("7 15 98") == "1998-07-15"
    assert _iso_date("3 1 05") == "2005-03-01"


# --- finding 9: depth-chain continuity tamper ---------------------------------

def test_detects_broken_depth_chain_continuity(tmp_path):
    import re
    import zipfile
    prj = _project([_shot("E", "S1", inc=-30.0, length=100.0),
                    _shot("S1", "S2", inc=-30.0, length=100.0)])
    d = map_project(prj, report=ConversionReport("s", "o"))
    out = tmp_path / "o.tml"
    write_tml(d, out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("Data.xml").decode()
    # break the chain: S2's DepthIn no longer equals S1's Depth,
    # while keeping S2's own delta self-consistent
    xml = re.sub(r"<DepthIn>50</DepthIn>", "<DepthIn>70</DepthIn>", xml)
    xml = re.sub(r"<Depth>100</Depth>", "<Depth>120</Depth>", xml)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("Data.xml", xml)
    assert any("disagrees with parent" in p for p in reconcile(prj, out))
