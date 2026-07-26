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


PLACEHOLDER_ROW = (
    "Cave\r\n"
    "SURVEY NAME: A\r\n"
    "SURVEY DATE: 11 25 2022  COMMENT:\r\n"
    "SURVEY TEAM: \r\n"
    "\r\n"
    "DECLINATION:    0.00  FORMAT: DMMDLRUDLADNT  CORRECTIONS:  0.00 0.00 0.00  CORRECTIONS2:  0.00 0.00\r\n"
    "\r\n"
    "FROM TO LENGTH BEARING INC LEFT UP DOWN RIGHT FLAGS COMMENTS\r\n"
    "\r\n"
    "        From Station           To Station     0.00     0.00     0.00     0.00     0.00     0.00     0.00\r\n"
    "                   0                 2001    75.46     0.00   -23.00     0.00     0.00     0.00     0.00\r\n"
)


def test_compass_editor_placeholder_row_is_skipped():
    # Seen in real files (Indian data.dat): Compass's editor template row.
    dat = parse_dat_text(PLACEHOLDER_ROW, file="q.dat")
    sv = dat.surveys[0]
    assert len(sv.shots) == 1
    assert sv.shots[0].from_station == "0"
    assert sv.placeholder_lines == (10,)


def test_blank_cave_name_line():
    dat = parse_dat_text(BLANK_CAVE_NAME, file="q.dat")
    sv = dat.surveys[0]
    assert sv.cave_name == ""
    assert sv.name == "T3"
    assert sv.team == ()
    assert len(sv.shots) == 1
