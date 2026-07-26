import pytest

from speleoconvert.compass.model import ParseError
from speleoconvert.compass.parser_dat import parse_dat, parse_dat_text

SURVEY_A = (
    "oubliette\r\n"
    "SURVEY NAME: oubliette\r\n"
    "SURVEY DATE: 2 23 2024  COMMENT:first dive\r\n"
    "SURVEY TEAM: \r\n"
    "Matt Hansen,J Doe\r\n"
    "DECLINATION:   -6.13  FORMAT: DDDWLRUDLAaDdNF  CORRECTIONS:  1.00 2.00 3.00"
    "  CORRECTIONS2:  4.00 5.00\r\n"
    "\r\n"
    "                FROM                   TO   LENGTH  BEARING      INC     LEFT"
    "       UP     DOWN    RIGHT   FLAGS  COMMENTS\r\n"
    "\r\n"
    "                  L1                   L2   110.00   338.00     1.56    -9.90"
    "     3.00     3.00     8.00\r\n"
    "                  L2                   L3    77.00   336.00     8.97    20.00"
    "     0.00     6.00    30.00  #|PC#  tricky spot\r\n"
)

SURVEY_B = (
    "oubliette\r\n"
    "SURVEY NAME: SIDE\r\n"
    "SURVEY DATE: 1 1 2001  COMMENT:\r\n"
    "SURVEY TEAM: \r\n"
    "?\r\n"
    "DECLINATION:    0.00  FORMAT: DDDDUDRLLADN\r\n"
    "\r\n"
    "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n"
    "\r\n"
    "                  S1                   S2    10.00    90.00     0.00     1.00"
    "     1.00     1.00     1.00\r\n"
)

TWO_SURVEYS = SURVEY_A + "\x0c" + SURVEY_B + "\x1a"


def test_parses_two_surveys():
    dat = parse_dat_text(TWO_SURVEYS, file="oubliette.DAT")
    assert len(dat.surveys) == 2
    a, b = dat.surveys
    assert a.cave_name == "oubliette"
    assert a.name == "oubliette"
    assert a.date_raw == "2 23 2024"
    assert a.comment == "first dive"
    assert a.team == ("Matt Hansen", "J Doe")
    assert a.declination_deg == -6.13
    assert a.corrections == (1.0, 2.0, 3.0)
    assert a.corrections2 == (4.0, 5.0)
    assert b.team == ()          # "?" means unknown
    assert b.corrections is None


def test_shot_fields_and_sentinels():
    dat = parse_dat_text(TWO_SURVEYS, file="oubliette.DAT")
    s1, s2 = dat.surveys[0].shots
    assert (s1.from_station, s1.to_station) == ("L1", "L2")
    assert s1.length_ft == 110.0 and s1.bearing_deg == 338.0
    assert s1.left_ft is None            # -9.90 sentinel
    assert s1.up_ft == 3.0 and s1.down_ft == 3.0 and s1.right_ft == 8.0
    assert s1.flags.raw == "" and s1.comment == ""
    assert s2.flags.exclude_plot and s2.flags.no_adjust
    assert s2.comment == "tricky spot"
    # column layout: header said LEFT UP DOWN RIGHT -> fields land accordingly
    assert dat.surveys[1].shots[0].left_ft == 1.0


def test_bad_header_is_parse_error():
    broken = TWO_SURVEYS.replace("LENGTH  BEARING", "BEARING  LENGTH", 1)
    with pytest.raises(ParseError) as e:
        parse_dat_text(broken, file="x.dat")
    assert "column header" in str(e.value)


def test_malformed_shot_line_reports_location():
    broken = SURVEY_A + "                  L9\r\n"
    with pytest.raises(ParseError) as e:
        parse_dat_text(broken, file="x.dat")
    assert "x.dat:" in str(e.value)


def test_backsight_columns_detected():
    bs = SURVEY_A.replace(
        "     LEFT       UP     DOWN    RIGHT   FLAGS",
        "     LEFT       UP     DOWN    RIGHT     AZM2     INC2   FLAGS",
    ).replace(
        "     3.00     3.00     8.00\r\n",
        "     3.00     3.00     8.00   158.00    -1.50\r\n",
    ).replace(
        "     0.00     6.00    30.00  #|PC#  tricky spot\r\n",
        "     0.00     6.00    30.00  -999.25  -999.25  #|PC#  tricky spot\r\n",
    )
    dat = parse_dat_text(bs, file="bs.dat")
    sv = dat.surveys[0]
    assert sv.has_backsight_columns
    assert sv.shots[0].azm2_deg == 158.0 and sv.shots[0].inc2_deg == -1.5
    assert sv.shots[1].azm2_deg is None and sv.shots[1].inc2_deg is None


def test_parse_dat_reads_cp437(tmp_path):
    p = tmp_path / "enc.dat"
    p.write_bytes(TWO_SURVEYS.encode("cp437"))
    dat = parse_dat(p)
    assert dat.path.endswith("enc.dat")
