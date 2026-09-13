"""Folium map rendering for the delay/loiter/waypoint geometry."""

from __future__ import annotations

from typing import Optional

import folium

from .geometry import LatLon, LocalFrame, NorthEast
from .motion import CircularLoiter, InterceptSolution, StraightTrack, UASDelayMotion

PATH_SAMPLES = 80
LOITER_CIRCLE_SAMPLES = 144


def sample_positions(
    motion: UASDelayMotion | StraightTrack,
    end_time_s: float,
    samples: int,
) -> list[NorthEast]:
    """Sample the motion model for map drawing."""
    count = max(samples, 2)
    return [
        motion.position_at(end_time_s * index / (count - 1))
        for index in range(count)
    ]


def map_coordinates(
    frame: LocalFrame,
    positions: list[NorthEast],
) -> list[list[float]]:
    """Return Folium coordinate order: [latitude, longitude]."""
    coordinates: list[list[float]] = []
    for position in positions:
        geo = frame.to_latlon(position)
        coordinates.append([geo.lat_deg, geo.lon_deg])
    return coordinates


def popup_latlon(label: str, point: LatLon, extra: str = "") -> str:
    extra_html = f"<br>{extra}" if extra else ""
    return (
        f"<b>{label}</b><br>"
        f"Lat: {point.lat_deg:.7f}<br>"
        f"Lon: {point.lon_deg:.7f}"
        f"{extra_html}"
    )


def add_marker(
    map_object: folium.Map,
    point: LatLon,
    label: str,
    color: str,
    icon: str,
    extra_popup: str = "",
) -> None:
    folium.Marker(
        location=[point.lat_deg, point.lon_deg],
        tooltip=label,
        popup=folium.Popup(
            popup_latlon(label, point, extra_popup), max_width=320
        ),
        icon=folium.Icon(color=color, icon=icon, prefix="fa"),
    ).add_to(map_object)


def create_map(
    frame: LocalFrame,
    uas_delay_motion: UASDelayMotion,
    target: StraightTrack,
    delay_s: float,
    report_time_s: float,
    solution: Optional[InterceptSolution],
) -> folium.Map:
    """Build an interactive map of the planned delay and waypoint geometry."""
    map_object = folium.Map(
        location=[frame.origin.lat_deg, frame.origin.lon_deg],
        zoom_start=13,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    uas_now = uas_delay_motion.position_at(0.0)
    target_now = target.position_at(0.0)
    uas_engagement = uas_delay_motion.position_at(delay_s)
    target_engagement = target.position_at(delay_s)
    target_report = target.position_at(report_time_s)

    uas_now_geo = frame.to_latlon(uas_now)
    target_now_geo = frame.to_latlon(target_now)
    uas_engagement_geo = frame.to_latlon(uas_engagement)
    target_engagement_geo = frame.to_latlon(target_engagement)
    target_report_geo = frame.to_latlon(target_report)

    add_marker(
        map_object,
        uas_now_geo,
        "UAS now",
        "blue",
        "plane",
        extra_popup=(
            f"Current ground track: {uas_delay_motion.bearing_at(0.0):.1f}°"
        ),
    )
    add_marker(map_object, target_now_geo, "Target now", "red", "ship")
    add_marker(
        map_object,
        uas_engagement_geo,
        f"UAS at engagement ({delay_s:.1f} s)",
        "cadetblue",
        "play",
        extra_popup=(
            f"Tangent track: {uas_delay_motion.bearing_at(delay_s):.1f}°"
        ),
    )
    add_marker(
        map_object,
        target_engagement_geo,
        f"Target at engagement ({delay_s:.1f} s)",
        "lightred",
        "play",
    )
    add_marker(
        map_object,
        target_report_geo,
        f"Target at requested time ({report_time_s:.1f} s)",
        "orange",
        "info-sign",
    )

    # Show the actual UAS path during delay: straight or circular loiter.
    delay_path = sample_positions(uas_delay_motion, delay_s, PATH_SAMPLES)
    delay_description = (
        "UAS loiter path during delay"
        if isinstance(uas_delay_motion, CircularLoiter)
        else "UAS straight-track propagation during delay"
    )
    folium.PolyLine(
        locations=map_coordinates(frame, delay_path),
        color="blue",
        weight=5,
        dash_array="8, 8",
        tooltip=f"{delay_description}: {delay_s:.1f} s",
    ).add_to(map_object)

    # Target propagation while the engagement command is delayed.
    folium.PolyLine(
        locations=map_coordinates(
            frame,
            [target_now, target_engagement],
        ),
        color="red",
        weight=4,
        dash_array="8, 8",
        tooltip=f"Target propagation during delay: {delay_s:.1f} s",
    ).add_to(map_object)

    # Loiter-specific geometry.
    extra_bounds_positions: list[NorthEast] = []
    if isinstance(uas_delay_motion, CircularLoiter):
        loiter = uas_delay_motion
        center_geo = frame.to_latlon(loiter.center)

        add_marker(
            map_object,
            center_geo,
            "Loiter center",
            "purple",
            "repeat",
            extra_popup=(
                f"Radius: {loiter.radius_m:.1f} m<br>"
                f"Direction: {loiter.turn_direction}<br>"
                f"Period: {loiter.period_s:.1f} s"
            ),
        )

        folium.Circle(
            location=[center_geo.lat_deg, center_geo.lon_deg],
            radius=loiter.radius_m,
            color="purple",
            weight=2,
            fill=False,
            dash_array="4, 8",
            tooltip=(
                f"Loiter circle: R={loiter.radius_m:.1f} m, "
                f"{loiter.turn_direction}"
            ),
        ).add_to(map_object)

        full_loiter = sample_positions(
            loiter,
            loiter.period_s,
            LOITER_CIRCLE_SAMPLES,
        )
        folium.PolyLine(
            locations=map_coordinates(frame, full_loiter),
            color="purple",
            weight=2,
            opacity=0.6,
            tooltip="Full loiter orbit",
        ).add_to(map_object)

        extra_bounds_positions.extend(full_loiter)

    # Target future path and the post-delay UAS route to waypoint.
    if solution is None:
        target_path_end_s = max(report_time_s, delay_s) + 120.0
        target_future_path = sample_positions(
            target,
            target_path_end_s,
            PATH_SAMPLES,
        )
        folium.PolyLine(
            locations=map_coordinates(frame, target_future_path),
            color="red",
            weight=3,
            opacity=0.75,
            tooltip="Projected target track: no reachable solution",
        ).add_to(map_object)
    else:
        waypoint_geo = frame.to_latlon(solution.waypoint)
        target_path_end_s = max(
            report_time_s,
            solution.total_time_from_now_s + 30.0,
        )
        target_future_path = sample_positions(
            target,
            target_path_end_s,
            PATH_SAMPLES,
        )
        folium.PolyLine(
            locations=map_coordinates(frame, target_future_path),
            color="red",
            weight=3,
            opacity=0.75,
            tooltip="Projected target ground track",
        ).add_to(map_object)

        folium.PolyLine(
            locations=map_coordinates(
                frame,
                [solution.uas_position_at_engagement, solution.waypoint],
            ),
            color="blue",
            weight=5,
            tooltip=(
                "Straight-line post-delay route to waypoint "
                f"({solution.time_after_engagement_s:.1f} s)"
            ),
        ).add_to(map_object)

        folium.Circle(
            location=[
                uas_engagement_geo.lat_deg,
                uas_engagement_geo.lon_deg,
            ],
            radius=solution.distance_after_engagement_m,
            color="blue",
            weight=2,
            fill=False,
            dash_array="5, 7",
            tooltip=(
                "Reachable distance after engagement: "
                f"{solution.distance_after_engagement_m:.0f} m"
            ),
        ).add_to(map_object)

        add_marker(
            map_object,
            waypoint_geo,
            "Computed waypoint",
            "green",
            "flag",
            extra_popup=(
                f"Arrival time from now: {solution.total_time_from_now_s:.1f} s<br>"
                f"Post-delay route bearing: {solution.command_bearing_deg:.1f}°"
            ),
        )

        radius = solution.distance_after_engagement_m
        extra_bounds_positions.extend(
            [
                solution.waypoint,
                NorthEast(
                    north_m=solution.uas_position_at_engagement.north_m + radius,
                    east_m=solution.uas_position_at_engagement.east_m,
                ),
                NorthEast(
                    north_m=solution.uas_position_at_engagement.north_m - radius,
                    east_m=solution.uas_position_at_engagement.east_m,
                ),
                NorthEast(
                    north_m=solution.uas_position_at_engagement.north_m,
                    east_m=solution.uas_position_at_engagement.east_m + radius,
                ),
                NorthEast(
                    north_m=solution.uas_position_at_engagement.north_m,
                    east_m=solution.uas_position_at_engagement.east_m - radius,
                ),
            ]
        )

    # Fit bounds around all relevant positions and orbit circle extrema.
    bounds_positions = [
        uas_now,
        target_now,
        uas_engagement,
        target_engagement,
        target_report,
        *extra_bounds_positions,
    ]
    bounds_geo = [frame.to_latlon(point) for point in bounds_positions]
    map_object.fit_bounds(
        [
            [
                min(point.lat_deg for point in bounds_geo),
                min(point.lon_deg for point in bounds_geo),
            ],
            [
                max(point.lat_deg for point in bounds_geo),
                max(point.lon_deg for point in bounds_geo),
            ],
        ]
    )

    folium.LayerControl().add_to(map_object)
    return map_object
