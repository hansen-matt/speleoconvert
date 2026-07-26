import math

import pytest

from speleoconvert.compass.model import (
    CompassDatFile,
    CompassProject,
    CompassShot,
    CompassSurvey,
    DatLink,
    FixedStation,
    FormatSpec,
    ShotFlags,
)
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport, StrictModeError

FMT = FormatSpec.parse("DDDWLRUDLAaDdNF", file="t.dat", line_no=1)


def _shot(frm, to, length=10.0, bearing=90.0, inc=0.0, **kw):
    defaults = dict(
        left_ft=1.0, up_ft=1.0, down_ft=1.0, right_ft=1.0,
        azm2_deg=None, inc2_deg=None, flags=ShotFlags(), comment="", line_no=10,
    )
    defaults.update(kw)
    return CompassShot(frm, to, length, bearing, inc, **defaults)


def _project(shots, fixed=(), datum="WGS 1984"):
    survey = CompassSurvey(
        cave_name="cave", name="A", date_raw="2 23 2024", comment="hi",
        team=("Matt",), declination_deg=-6.13, format=FMT,
        corrections=(1.0, 2.0, 3.0), corrections2=(4.0, 5.0),
        discovery_raw=None, has_backsight_columns=False,
        shots=tuple(shots), source_file="t.dat",
    )
    return CompassProject(
        mak_path="/tmp/test.mak", base_easting_m=0, base_northing_m=0,
        base_elevation_m=0, base_zone=17, convergence_deg=-1.14,
        datum=datum, flags_raw="gEv", comments=(),
        links=(DatLink("t.dat", datum, 17, tuple(fixed)),),
        dat_files=(CompassDatFile("t.dat", (survey,)),),
    )


def test_basic_chain_and_ids():
    prj = _project([_shot("E", "S1", inc=-45.0, length=10.0), _shot("S1", "S2")])
    r = ConversionReport("s", "o")
    d = map_project(prj, report=r)
    sec = d["sections"][0]
    types = [s["shot_type"] for s in sec["shots"]]
    assert types == ["START", "REAL", "REAL"]
    start, s1, s2 = sec["shots"]
    assert start["name"] == "E" and start["id_stop"] == 0
    assert s1["id_start"] == 0 and s1["id_stop"] == 1 and s1["name"] == "S1"
    assert s1["depth"] == pytest.approx(10.0 * math.sin(math.radians(45.0)), abs=1e-3)
    assert s2["depth_start"] == s1["depth"]
    assert sec["declination"] == -6.13
    assert sec["correction"] == [1.0, 2.0, 3.0]
    assert sec["compass_format"] == "DDDWLRUDLAaDdNF"
    assert sec["date"] == "2024-02-23"
    assert d["unit"] == "FT"


def test_loop_shot_stays_real_with_closure_ref():
    prj = _project([
        _shot("E", "A"), _shot("A", "B"), _shot("B", "E"),  # loop back to E
    ])
    d = map_project(prj, report=ConversionReport("s", "o"))
    last = d["sections"][0]["shots"][-1]
    # REAL so Ariane draws it as solid passage (CLOSURE renders dashed/excluded);
    # the tie is still encoded via closure_to_id and the duplicate station name.
    assert last["shot_type"] == "REAL"
    assert last["closure_to_id"] == 0  # E is the START shot, id 0
    assert last["name"] == "E"


def test_fixed_station_gets_latlon():
    fixed = [FixedStation("E", "f", 933560.866, 11070112.205, 0.0, raw="")]
    prj = _project([_shot("E", "S1")], fixed=fixed)
    d = map_project(prj, report=ConversionReport("s", "o"))
    start = d["sections"][0]["shots"][0]
    assert start["latitude"] == pytest.approx(30.48, abs=0.05)
    assert start["longitude"] == pytest.approx(-83.24, abs=0.05)


def test_flags_and_backsights_to_comment_lenient():
    shots = [
        _shot("E", "S1", flags=ShotFlags(exclude_length=True, raw="L"), comment="c"),
        _shot("S1", "S2", azm2_deg=158.0, inc2_deg=-1.5),
    ]
    r = ConversionReport("s", "o")
    d = map_project(_project(shots), report=r)
    s1, s2 = d["sections"][0]["shots"][1:]
    assert "Compass flags: #|L#" in s1["comment"] and "c" in s1["comment"]
    assert "Backsight: azm2=158.0 inc2=-1.5" in s2["comment"]
    cats = {e.category for e in r.non_native()}
    assert {"shot-flags", "backsight"} <= cats


def test_strict_mode_raises_on_backsight():
    shots = [_shot("E", "S1", azm2_deg=158.0, inc2_deg=None)]
    with pytest.raises(StrictModeError):
        map_project(_project(shots), strict=True, report=ConversionReport("s", "o"))


def test_strict_mode_ok_for_exempt_categories():
    shots = [_shot("E", "S1", left_ft=None)]  # lrud-missing is exempt
    d = map_project(_project(shots), strict=True, report=ConversionReport("s", "o"))
    assert d["sections"][0]["shots"][1]["left"] is None


def test_excluded_flag_native():
    shots = [_shot("E", "S1", flags=ShotFlags(exclude_all=True, raw="X"))]
    d = map_project(_project(shots), strict=True, report=ConversionReport("s", "o"))
    assert d["sections"][0]["shots"][1]["excluded"] is True


def test_unparseable_date_goes_to_comment():
    prj = _project([_shot("E", "S1")])
    survey = prj.dat_files[0].surveys[0]
    object.__setattr__(survey, "date_raw", "1 1 1")  # frozen; test-only poke
    r = ConversionReport("s", "o")
    d = map_project(prj, report=r)
    sec = d["sections"][0]
    assert sec["date"] is None
    assert "1 1 1" in sec["comment"]
