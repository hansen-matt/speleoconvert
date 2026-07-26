import pytest

from speleoconvert.compass.model import FixedStation
from speleoconvert.geodesy import GeodesyError, fixed_station_to_wgs84


def test_wgs84_feet_station_matches_known_point():
    # MBSP entrance area, UTM 17N (WGS84): 933560.866 ft E, 11070112.205 ft N
    fs = FixedStation("1E5", "f", 933560.866, 11070112.205, 0.0, raw="")
    lat, lon, elev = fixed_station_to_wgs84(fs, zone=17, datum="WGS 1984")
    # ~Madison Blue Spring, FL
    assert lat == pytest.approx(30.48, abs=0.05)
    assert lon == pytest.approx(-83.24, abs=0.05)
    assert elev == 0.0


def test_meters_station_no_unit_conversion():
    f_ft = FixedStation("A", "f", 933560.866, 11070112.205, 0.0, raw="")
    f_m = FixedStation("A", "m", 933560.866 * 0.3048, 11070112.205 * 0.3048, 0.0, raw="")
    a = fixed_station_to_wgs84(f_ft, 17, "WGS 1984")
    b = fixed_station_to_wgs84(f_m, 17, "WGS 1984")
    assert a[0] == pytest.approx(b[0], abs=1e-9)
    assert a[1] == pytest.approx(b[1], abs=1e-9)


def test_nad27_differs_from_wgs84():
    fs = FixedStation("A", "f", 933560.866, 11070112.205, 0.0, raw="")
    w = fixed_station_to_wgs84(fs, 17, "WGS 1984")
    n = fixed_station_to_wgs84(fs, 17, "North American 1927")
    # NAD27->WGS84 shift in Florida is tens of meters, not zero, not huge
    dlat = abs(w[0] - n[0]) * 111_000
    assert 5 < dlat < 300


def test_unknown_datum_raises():
    fs = FixedStation("A", "f", 1.0, 1.0, 0.0, raw="")
    with pytest.raises(GeodesyError):
        fixed_station_to_wgs84(fs, 17, "Tokyo Datum")
