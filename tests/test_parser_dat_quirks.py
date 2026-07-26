"""Regression tests for real-corpus quirks in .dat files."""
from speleoconvert.compass.parser_dat import parse_dat_text

BLANK_CAVE_NAME = (
    "\r\n"  # blank cave-name line (seen in Region_4.DAT)
    "SURVEY NAME: T3\r\n"
    "SURVEY DATE: 11 9 2014  COMMENT:\r\n"
    "SURVEY TEAM: \r\n"
    "\r\n"
    "DECLINATION: -4.14  FORMAT: DDDWUDLRLADN  CORRECTIONS: 0.00 0.00 0.00\r\n"
    "\r\n"
    "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n"
    "\r\n"
    "T1 T2 10.00 90.00 0.00 1.00 1.00 1.00 1.00\r\n"
)


def test_blank_cave_name_line():
    dat = parse_dat_text(BLANK_CAVE_NAME, file="q.dat")
    sv = dat.surveys[0]
    assert sv.cave_name == ""
    assert sv.name == "T3"
    assert sv.team == ()
    assert len(sv.shots) == 1
