import pytest

from speleoconvert.compass.model import ParseError
from speleoconvert.compass.parser_mak import load_project, parse_mak

MAK = (
    "@284551.100,3373992.300,0.000,17,-1.140;\r\n"
    "&WGS 1984;\r\n"
    "!gEvotScxpl;\r\n"
    "\r\n"
    "/\r\n"
    "$17;\r\n"
    "&North American 1927;\r\n"
    "*0.00;\r\n"
    "#Region_1.DAT,\r\n"
    " 1E5[f,933560.866,11070112.205,0.000],\r\n"
    " MZ0[m,284000.0,3373000.0,1.5];\r\n"
    "/ a trailing comment\r\n"
    "*0.00;\r\n"
    "#M3 Data.dat;\r\n"
)


def _write(tmp_path, text=MAK):
    p = tmp_path / "test.MAK"
    p.write_bytes(text.encode("cp437"))
    return p


def test_parse_mak_base_and_links(tmp_path):
    prj = parse_mak(_write(tmp_path))
    assert prj.base_easting_m == 284551.1
    assert prj.base_zone == 17
    assert prj.convergence_deg == -1.14
    assert prj.datum == "WGS 1984"
    assert prj.flags_raw == "gEvotScxpl"
    assert len(prj.links) == 2
    l1, l2 = prj.links
    assert l1.path == "Region_1.DAT"
    assert l1.datum == "North American 1927"   # per-link datum override
    assert l1.utm_zone == 17
    assert [f.name for f in l1.fixed_stations] == ["1E5", "MZ0"]
    assert l1.fixed_stations[0].unit == "f"
    assert l1.fixed_stations[1].unit == "m"
    assert l1.fixed_stations[1].z == 1.5
    assert l1.raw_params == ("*0.00",)
    assert l2.path == "M3 Data.dat"
    assert l2.fixed_stations == ()
    assert any(c.startswith("/") for c in prj.comments)


def test_unknown_directive_is_error(tmp_path):
    with pytest.raises(ParseError):
        parse_mak(_write(tmp_path, MAK + "^bogus;\r\n"))


def test_minimal_mak_without_base_datum_zone(tmp_path):
    prj = parse_mak(_write(tmp_path, "/just a comment\r\n#M2B.DAT;\r\n\x1a"))
    assert prj.base_easting_m is None
    assert prj.datum is None
    assert prj.links[0].path == "M2B.DAT"
    assert prj.links[0].datum is None and prj.links[0].utm_zone is None


def test_percent_param_and_bare_link_stations(tmp_path):
    text = MAK + "%0.00;\r\n#Extra.DAT,\r\n AgData17, 0[m,294496.5,3334364.16,0.0];\r\n"
    prj = parse_mak(_write(tmp_path, text))
    extra = prj.links[-1]
    assert extra.path == "Extra.DAT"
    assert extra.link_stations == ("AgData17",)
    assert [f.name for f in extra.fixed_stations] == ["0"]
    assert extra.raw_params == ("%0.00",)


def test_load_project_resolves_case_insensitive(tmp_path):
    p = _write(tmp_path)
    dat = (
        "cave\r\nSURVEY NAME: A\r\nSURVEY DATE: 1 1 2020  COMMENT:\r\n"
        "SURVEY TEAM: \r\n\r\n"
        "DECLINATION: 0.00  FORMAT: DDDDUDRLLADN\r\n\r\n"
        "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n\r\n"
        "A1 A2 10.00 90.00 0.00 1.00 1.00 1.00 1.00\r\n"
    )
    # note different case vs link names
    (tmp_path / "REGION_1.dat").write_bytes(dat.encode("cp437"))
    (tmp_path / "m3 data.DAT").write_bytes(dat.encode("cp437"))
    prj = load_project(p)
    assert len(prj.dat_files) == 2
    assert prj.dat_files[0].surveys[0].name == "A"


def test_load_project_missing_dat_is_error(tmp_path):
    with pytest.raises(ParseError) as e:
        load_project(_write(tmp_path))
    assert "Region_1.DAT" in str(e.value)
