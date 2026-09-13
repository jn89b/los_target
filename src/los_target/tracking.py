"""Estimate target bearing/speed from cached position history."""

from __future__ import annotations

from .geometry import LatLon, LocalFrame
from .motion import bearing_from_to_deg
from .storage import TargetEntry


def estimate_bearing_speed(history: list[TargetEntry]) -> tuple[float, float]:
    """Estimate (bearing_deg, speed_mps) from the earliest and latest entries."""
    if len(history) < 2:
        raise ValueError("At least 2 history entries are required to estimate motion.")

    ordered = sorted(history, key=lambda entry: entry.timestamp)
    first, last = ordered[0], ordered[-1]

    delta_time_s = (last.timestamp - first.timestamp).total_seconds()
    if delta_time_s <= 0.0:
        raise ValueError("History entries must have increasing timestamps.")

    first_point = LatLon(lat_deg=first.lat_deg, lon_deg=first.lon_deg)
    last_point = LatLon(lat_deg=last.lat_deg, lon_deg=last.lon_deg)

    frame = LocalFrame.centered_at(first_point)
    start_local = frame.to_local(first_point)
    end_local = frame.to_local(last_point)

    bearing_deg = bearing_from_to_deg(start_local, end_local)
    speed_mps = (end_local - start_local).magnitude() / delta_time_s
    return bearing_deg, speed_mps
