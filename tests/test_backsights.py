import pytest

from speleoconvert.compass.backsights import (
    average_azimuth,
    average_inclination,
    detect_backsight_convention,
)
from speleoconvert.mapping import map_project
from speleoconvert.report import ConversionReport
from tests.test_mapping import _project, _shot

# --- averaging ---------------------------------------------------------------

def test_average_azimuth_uncorrected_flips_backsight():
    # fore 340, raw back 162 -> flipped 342 -> mean 341
    assert average_azimuth(340.0, 162.0, corrected=False) == pytest.approx(341.0)


def test_average_azimuth_corrected_used_as_is():
    assert average_azimuth(340.0, 342.0, corrected=True) == pytest.approx(341.0)


def test_average_azimuth_wraps_north():
    # fore 358, flipped back 4 -> circular mean 1, not 181
    assert average_azimuth(358.0, 184.0, corrected=False) == pytest.approx(1.0)


def test_average_inclination_uncorrected_negates():
    assert average_inclination(5.0, -4.8, corrected=False) == pytest.approx(4.9)


def test_average_inclination_corrected():
    assert average_inclination(5.0, 4.8, corrected=True) == pytest.approx(4.9)


# --- detection ---------------------------------------------------------------

def _bs_shots(pairs, inc_pairs=None):
    inc_pairs = inc_pairs or [(0.0, 0.0)] * len(pairs)
    return [
        _shot(f"S{i}", f"S{i+1}", bearing=az, inc=inc, azm2_deg=az2, inc2_deg=inc2)
        for i, ((az, az2), (inc, inc2)) in enumerate(zip(pairs, inc_pairs, strict=True))
    ]


def test_detect_uncorrected():
    prj = _project(_bs_shots([(10.0, 191.0), (250.0, 69.5), (359.0, 178.0)],
                             [(5.0, -4.5), (-12.0, 12.4), (0.5, -0.2)]))
    conv = detect_backsight_convention(prj.dat_files[0].surveys[0])
    assert conv.azimuth_corrected is False
    assert conv.inclination_corrected is False


def test_detect_corrected():
    prj = _project(_bs_shots([(10.0, 11.0), (250.0, 249.5), (359.0, 358.0)],
                             [(5.0, 4.5), (-12.0, -12.4), (30.5, 30.2)]))
    conv = detect_backsight_convention(prj.dat_files[0].surveys[0])
    assert conv.azimuth_corrected is True
    assert conv.inclination_corrected is True


def test_detect_defaults_to_uncorrected_without_data():
    prj = _project([_shot("A", "B")])
    conv = detect_backsight_convention(prj.dat_files[0].surveys[0])
    assert conv.azimuth_corrected is False
    assert conv.inclination_corrected is False


# --- mapping integration -----------------------------------------------------

def test_mapping_averages_backsights():
    shots = [_shot("E", "S1", bearing=340.0, inc=5.0, azm2_deg=162.0, inc2_deg=-4.8)]
    r = ConversionReport("s", "o")
    d = map_project(_project(shots), report=r)
    sh = d["sections"][0]["shots"][1]
    assert sh["azimuth"] == pytest.approx(341.0)
    assert sh["inclination"] == pytest.approx(4.9)
    assert "azm2=162.0" in sh["comment"]          # raw readings preserved
    assert any(e.category == "backsight-averaged" for e in r.entries)


def test_mapping_recovers_missing_foresight_from_backsight():
    shots = [_shot("E", "S1", bearing=None, azm2_deg=162.0)]
    r = ConversionReport("s", "o")
    # convention defaults to uncorrected -> azimuth = 162 + 180 = 342
    d = map_project(_project(shots), report=r)
    assert d["sections"][0]["shots"][1]["azimuth"] == pytest.approx(342.0)
    assert any(e.category == "bearing-from-backsight" for e in r.entries)


def test_mapping_flags_large_discrepancy():
    shots = [
        _shot("E", "S1", bearing=340.0, azm2_deg=162.0),   # 2 deg off: fine
        _shot("S1", "S2", bearing=100.0, azm2_deg=295.0),  # 15 deg off: flagged
    ]
    r = ConversionReport("s", "o")
    map_project(_project(shots), report=r)
    flagged = [e for e in r.entries if e.category == "backsight-discrepancy"]
    assert len(flagged) == 1


def test_backsights_pass_strict_mode():
    shots = [_shot("E", "S1", bearing=340.0, azm2_deg=162.0, inc2_deg=0.0)]
    d = map_project(_project(shots), strict=True, report=ConversionReport("s", "o"))
    assert d["sections"][0]["shots"][1]["azimuth"] == pytest.approx(341.0)
