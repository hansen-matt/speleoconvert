"""UTM+datum -> WGS84 for Compass .mak fixed stations. Only module using pyproj."""
from __future__ import annotations

from functools import lru_cache

from pyproj import Transformer

from speleoconvert.compass.model import FixedStation

FT_TO_M = 0.3048  # international foot (documented decision; US-survey-foot delta ~2 ppm)

_DATUM_EPSG_BASE = {
    "WGS 1984": 32600,
    "North American 1983": 26900,
    "North American 1927": 26700,
}


class GeodesyError(Exception):
    pass


@lru_cache(maxsize=32)
def _transformer(datum: str, zone: int) -> Transformer:
    try:
        base = _DATUM_EPSG_BASE[datum]
    except KeyError:
        raise GeodesyError(
            f"unsupported datum {datum!r} (known: {sorted(_DATUM_EPSG_BASE)})"
        ) from None
    if not 1 <= zone <= 60:
        raise GeodesyError(f"bad UTM zone {zone}")
    return Transformer.from_crs(f"EPSG:{base + zone}", "EPSG:4326", always_xy=True)


def fixed_station_to_wgs84(
    fs: FixedStation, zone: int, datum: str
) -> tuple[float, float, float]:
    scale = FT_TO_M if fs.unit == "f" else 1.0
    x_m, y_m, z_m = fs.x * scale, fs.y * scale, fs.z * scale
    lon, lat = _transformer(datum, zone).transform(x_m, y_m)
    return lat, lon, z_m


def utm_to_wgs84(
    easting_m: float, northing_m: float, zone: int, datum: str
) -> tuple[float, float]:
    """UTM meters -> (lat, lon). Used for the .mak base location."""
    lon, lat = _transformer(datum, zone).transform(easting_m, northing_m)
    return lat, lon
