"""Parsing/formatting for decimal-degree and 8-digit MGRS grid coordinates."""

from __future__ import annotations

import re

import mgrs as mgrs_lib

from .geometry import LatLon

_MGRS_CONVERTER = mgrs_lib.MGRS()

# "lat, lon" or "lat lon", each optionally followed by a hemisphere letter.
_DECIMAL_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*([NnSs]?)\s*[,\s]\s*"
    r"([+-]?\d+(?:\.\d+)?)\s*([EeWw]?)\s*$"
)


def _try_parse_decimal(raw: str) -> LatLon | None:
    match = _DECIMAL_RE.match(raw)
    if match is None:
        return None

    lat_value, lat_hemi, lon_value, lon_hemi = match.groups()
    lat_deg = float(lat_value) * (-1.0 if lat_hemi.upper() == "S" else 1.0)
    lon_deg = float(lon_value) * (-1.0 if lon_hemi.upper() == "W" else 1.0)
    return LatLon(lat_deg=lat_deg, lon_deg=lon_deg)


def _parse_mgrs(raw: str) -> LatLon:
    compact = re.sub(r"\s+", "", raw).upper()
    digit_run = re.search(r"\d+$", compact)
    if digit_run is None or len(digit_run.group()) != 8:
        raise ValueError(
            "MGRS grid coordinate must end with exactly 8 digits "
            f"(4-digit easting + 4-digit northing), got: {raw!r}"
        )

    try:
        lat_deg, lon_deg = _MGRS_CONVERTER.toLatLon(compact)
    except Exception as exc:  # mgrs raises plain Exception/RuntimeError on bad input
        raise ValueError(f"Could not parse MGRS grid coordinate {raw!r}: {exc}") from exc

    return LatLon(lat_deg=lat_deg, lon_deg=lon_deg)


def parse_coordinate(raw: str) -> LatLon:
    """Parse a decimal-degree pair or an 8-digit MGRS grid string into a LatLon."""
    if not raw or not raw.strip():
        raise ValueError("Coordinate input is empty.")

    decimal_point = _try_parse_decimal(raw)
    if decimal_point is not None:
        decimal_point.validate()
        return decimal_point

    point = _parse_mgrs(raw)
    point.validate()
    return point


def format_mgrs(point: LatLon) -> str:
    """Format a LatLon as an 8-digit-precision MGRS grid string."""
    return _MGRS_CONVERTER.toMGRS(point.lat_deg, point.lon_deg, MGRSPrecision=4)
