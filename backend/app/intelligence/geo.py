"""Coordinate extraction from entity values/metadata."""
from __future__ import annotations

import re

_LATLON_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def _valid(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def extract_coords(value: str | None, meta: dict | None) -> tuple[float, float] | None:
    """Return (lat, lon) from metadata keys or a 'lat,lon' value, else None."""
    meta = meta or {}
    for lat_key, lon_key in (("lat", "lon"), ("latitude", "longitude"), ("lat", "lng")):
        if lat_key in meta and lon_key in meta:
            try:
                lat, lon = float(meta[lat_key]), float(meta[lon_key])
                if _valid(lat, lon):
                    return (lat, lon)
            except (TypeError, ValueError):
                pass
    if value:
        m = _LATLON_RE.match(value)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if _valid(lat, lon):
                return (lat, lon)
    return None
