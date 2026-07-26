import math

from speleoconvert.compass.plt import parse_plt
from speleoconvert.verify import compare, compute_positions
from tests.test_mapping import _project, _shot

PLT = (
    "Z -100 100 -100 100 -50 0\r\n"
    "NX D 1 1 1 C\r\n"
    "M 0.0 0.0 0.0 SE P -9 -9 -9 -9 I 0.0\r\n"
    "D 0.0 10.0 0.0 SS1 P 1 1 1 1 I 10.0\r\n"
)


def test_parse_plt(tmp_path):
    p = tmp_path / "x.plt"
    p.write_bytes(PLT.encode("cp437"))
    st = parse_plt(p)
    assert st["E"] == (0.0, 0.0, 0.0)
    assert st["S1"] == (0.0, 10.0, 0.0)


def test_compute_positions_east_shot():
    # bearing 90 + declination -6.13 => true bearing 83.87
    prj = _project([_shot("E", "S1", length=10.0, bearing=90.0, inc=0.0)])
    pos = compute_positions(prj)
    tb = math.radians(90.0 - 6.13)
    assert pos["S1"][0] == round(10.0 * math.cos(tb), 6)  # north
    assert pos["S1"][1] == round(10.0 * math.sin(tb), 6)  # east


def test_compare_zero_error_against_self():
    prj = _project([_shot("E", "S1", length=10.0, bearing=90.0, inc=0.0)])
    pos = compute_positions(prj)
    stats = compare(prj, pos)
    assert stats["max_err_ft"] == 0.0 and stats["n"] == 2
