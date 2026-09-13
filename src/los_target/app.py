"""Streamlit UI: enter target/ownship data and compute the intercept waypoint."""

from __future__ import annotations

from datetime import datetime

import streamlit as st
from streamlit_folium import st_folium

from los_target.coordinates import format_mgrs, parse_coordinate
from los_target.geometry import LatLon, LocalFrame, average_latlon
from los_target.mapping import create_map
from los_target.motion import CircularLoiter, StraightTrack, calculate_waypoint, offset_from_center
from los_target.storage import TargetEntry, append_solution_record, append_target_entry, load_target_history
from los_target.tracking import estimate_bearing_speed

st.set_page_config(page_title="LOS Target Waypoint Planner", layout="wide")
st.title("LOS Target Waypoint Planner")

st.caption(
    "Coordinates accept decimal degrees (e.g. `11.3283, 146.2276`) or an "
    "8-digit MGRS grid (e.g. `57PWL1234567890` -> 4-digit easting + "
    "4-digit northing)."
)

# =====================================================================
# 1. Target entry + cache
# =====================================================================
st.header("1. Target location")

with st.form("target_entry_form"):
    col1, col2 = st.columns(2)
    target_id = col1.text_input("Target ID", value="TARGET-1")
    target_coord_raw = col2.text_input("Target location", key="target_coord_raw")

    col3, col4 = st.columns(2)
    entry_date = col3.date_input("Entry date", value=datetime.now().date())
    entry_time = col4.time_input(
        "Entry time", value=datetime.now().time().replace(microsecond=0)
    )

    save_target = st.form_submit_button("Save target entry")

if save_target:
    try:
        target_point = parse_coordinate(target_coord_raw)
        entry_timestamp = datetime.combine(entry_date, entry_time)
        append_target_entry(
            TargetEntry(
                target_id=target_id,
                timestamp=entry_timestamp,
                lat_deg=target_point.lat_deg,
                lon_deg=target_point.lon_deg,
                raw_input=target_coord_raw,
            )
        )
        st.success(
            f"Saved target entry at {target_point.lat_deg:.6f}, "
            f"{target_point.lon_deg:.6f} ({entry_timestamp.isoformat()})"
        )
    except ValueError as exc:
        st.error(str(exc))

target_history = load_target_history(target_id)
if target_history:
    st.dataframe(
        [
            {
                "timestamp": entry.timestamp.isoformat(),
                "lat_deg": entry.lat_deg,
                "lon_deg": entry.lon_deg,
                "raw_input": entry.raw_input,
            }
            for entry in target_history
        ],
        use_container_width=True,
    )
else:
    st.info("No cached history yet for this target ID.")

# =====================================================================
# 2. Target motion
# =====================================================================
st.header("2. Target motion")

motion_mode = st.radio(
    "Target bearing/speed source",
    ["Estimate from history", "Enter manually"],
    horizontal=True,
)

estimated_bearing_deg = 0.0
estimated_speed_mps = 0.0
if motion_mode == "Estimate from history":
    if len(target_history) < 2:
        st.warning(
            "Need at least 2 saved entries for this target ID to estimate motion."
        )
    else:
        try:
            estimated_bearing_deg, estimated_speed_mps = estimate_bearing_speed(
                target_history
            )
            st.info(
                f"Estimated from history: speed={estimated_speed_mps:.2f} m/s, "
                f"bearing={estimated_bearing_deg:.1f}°"
            )
        except ValueError as exc:
            st.error(str(exc))

col5, col6 = st.columns(2)
target_speed_mps = col5.number_input(
    "Target speed (m/s)", min_value=0.0, value=float(round(estimated_speed_mps, 2))
)
target_bearing_deg = col6.number_input(
    "Target bearing (deg, from true north)",
    min_value=0.0,
    max_value=360.0,
    value=float(round(estimated_bearing_deg, 1)),
)

if not target_history:
    st.stop()

latest_target = target_history[-1]
target_geo = LatLon(lat_deg=latest_target.lat_deg, lon_deg=latest_target.lon_deg)

# =====================================================================
# 3. Ownship / UAS
# =====================================================================
st.header("3. Ownship / UAS")

uas_mode = st.radio("UAS delay mode", ["LOITER", "STRAIGHT"], horizontal=True)

uas_speed_mps = st.number_input("UAS airspeed (m/s)", min_value=0.1, value=25.0)

uas_initial_geo: LatLon | None = None
loiter_center_geo: LatLon | None = None
loiter_radius_m = 200.0
turn_direction = "CW"
loiter_position_mode = "RADIAL_BEARING_FROM_CENTER"
loiter_radial_bearing_deg = 0.0
straight_bearing_deg = 0.0

if uas_mode == "LOITER":
    col7, col8 = st.columns(2)
    loiter_center_raw = col7.text_input("Loiter center location")
    loiter_radius_m = col8.number_input(
        "Loiter radius (m)", min_value=1.0, value=200.0
    )

    col9, col10 = st.columns(2)
    turn_direction = col9.radio("Turn direction", ["CW", "CCW"], horizontal=True)
    loiter_position_mode = col10.radio(
        "UAS current position",
        ["RADIAL_BEARING_FROM_CENTER", "UAS_INITIAL_LAT_LON"],
        help=(
            "RADIAL_BEARING_FROM_CENTER: give the bearing from the loiter "
            "center to the UAS. UAS_INITIAL_LAT_LON: give the UAS's own "
            "coordinate; it must lie ~on the loiter circle."
        ),
    )

    if loiter_position_mode == "RADIAL_BEARING_FROM_CENTER":
        loiter_radial_bearing_deg = st.number_input(
            "Radial bearing from loiter center to UAS (deg)",
            min_value=0.0,
            max_value=360.0,
            value=0.0,
        )
    else:
        uas_initial_raw = st.text_input("UAS current location")

    if loiter_center_raw:
        try:
            loiter_center_geo = parse_coordinate(loiter_center_raw)
        except ValueError as exc:
            st.error(str(exc))

    if loiter_position_mode == "UAS_INITIAL_LAT_LON" and uas_initial_raw:
        try:
            uas_initial_geo = parse_coordinate(uas_initial_raw)
        except ValueError as exc:
            st.error(str(exc))
else:
    col7, col8 = st.columns(2)
    uas_initial_raw = col7.text_input("UAS current location")
    straight_bearing_deg = col8.number_input(
        "UAS bearing (deg, from true north)",
        min_value=0.0,
        max_value=360.0,
        value=70.0,
    )
    if uas_initial_raw:
        try:
            uas_initial_geo = parse_coordinate(uas_initial_raw)
        except ValueError as exc:
            st.error(str(exc))

# =====================================================================
# 4. Timing
# =====================================================================
st.header("4. Timing")

col11, col12 = st.columns(2)
engagement_delay_s = col11.number_input(
    "Engagement delay (s)", min_value=0.0, value=60.0
)
target_report_time_s = col12.number_input(
    "Target report time (s from now)", min_value=0.0, value=120.0
)

generate_map = st.checkbox("Generate map after computing", value=True)

# =====================================================================
# 5. Compute
# =====================================================================
st.header("5. Compute waypoint")

if "last_result" not in st.session_state:
    st.session_state["last_result"] = None

if st.button("Compute waypoint", type="primary"):
    if uas_mode == "LOITER" and loiter_center_geo is None:
        st.error("Enter a valid loiter center location.")
        st.stop()
    if uas_mode == "STRAIGHT" and uas_initial_geo is None:
        st.error("Enter a valid UAS current location.")
        st.stop()
    if loiter_position_mode == "UAS_INITIAL_LAT_LON" and uas_initial_geo is None:
        st.error("Enter a valid UAS current location.")
        st.stop()

    origin_points = [target_geo]
    if uas_mode == "LOITER":
        origin_points.append(loiter_center_geo)
        if uas_initial_geo is not None:
            origin_points.append(uas_initial_geo)
    else:
        origin_points.append(uas_initial_geo)

    frame = LocalFrame.centered_at(average_latlon(origin_points))

    try:
        if uas_mode == "STRAIGHT":
            uas_delay_motion = StraightTrack(
                position=frame.to_local(uas_initial_geo),
                speed_mps=uas_speed_mps,
                bearing_deg=straight_bearing_deg,
            )
        else:
            loiter_center = frame.to_local(loiter_center_geo)
            if loiter_position_mode == "RADIAL_BEARING_FROM_CENTER":
                initial_position = offset_from_center(
                    center=loiter_center,
                    distance_m=loiter_radius_m,
                    bearing_deg=loiter_radial_bearing_deg,
                )
            else:
                initial_position = frame.to_local(uas_initial_geo)

            uas_delay_motion = CircularLoiter(
                center=loiter_center,
                radius_m=loiter_radius_m,
                speed_mps=uas_speed_mps,
                turn_direction=turn_direction,
                initial_position=initial_position,
            )
            uas_delay_motion.validate(radial_tolerance_m=25.0)

        target = StraightTrack(
            position=frame.to_local(target_geo),
            speed_mps=target_speed_mps,
            bearing_deg=target_bearing_deg,
        )

        solution = calculate_waypoint(
            uas_delay_motion=uas_delay_motion,
            target=target,
            engagement_delay_s=engagement_delay_s,
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    if solution is None:
        st.session_state["last_result"] = None
        st.error("No reachable waypoint found for these inputs.")
        st.stop()

    waypoint_geo = frame.to_latlon(solution.waypoint)

    append_solution_record(
        {
            "computed_at": datetime.now().isoformat(),
            "target_id": target_id,
            "target": {"lat_deg": target_geo.lat_deg, "lon_deg": target_geo.lon_deg},
            "target_speed_mps": target_speed_mps,
            "target_bearing_deg": target_bearing_deg,
            "uas_mode": uas_mode,
            "uas_speed_mps": uas_speed_mps,
            "engagement_delay_s": engagement_delay_s,
            "waypoint": {
                "lat_deg": waypoint_geo.lat_deg,
                "lon_deg": waypoint_geo.lon_deg,
                "mgrs": format_mgrs(waypoint_geo),
            },
            "total_time_from_now_s": solution.total_time_from_now_s,
            "command_bearing_deg": solution.command_bearing_deg,
        }
    )

    # Persist across reruns (e.g. panning the map) so the result stays visible.
    st.session_state["last_result"] = {
        "frame": frame,
        "uas_delay_motion": uas_delay_motion,
        "target": target,
        "solution": solution,
        "waypoint_geo": waypoint_geo,
        "engagement_delay_s": engagement_delay_s,
        "target_report_time_s": target_report_time_s,
        "generate_map": generate_map,
    }

result = st.session_state["last_result"]
if result is not None:
    solution = result["solution"]
    waypoint_geo = result["waypoint_geo"]

    st.success("Waypoint computed.")
    res_col1, res_col2, res_col3 = st.columns(3)
    res_col1.metric("Waypoint latitude", f"{waypoint_geo.lat_deg:.7f}")
    res_col2.metric("Waypoint longitude", f"{waypoint_geo.lon_deg:.7f}")
    res_col3.metric("Waypoint MGRS", format_mgrs(waypoint_geo))

    st.write(
        f"- Time after engagement: {solution.time_after_engagement_s:.2f} s\n"
        f"- Total time from now: {solution.total_time_from_now_s:.2f} s\n"
        f"- Post-delay route distance: {solution.distance_after_engagement_m:.1f} m\n"
        f"- Command bearing from engagement point: "
        f"{solution.command_bearing_deg:.1f}°"
    )

    if result["generate_map"]:
        map_object = create_map(
            frame=result["frame"],
            uas_delay_motion=result["uas_delay_motion"],
            target=result["target"],
            delay_s=result["engagement_delay_s"],
            report_time_s=result["target_report_time_s"],
            solution=solution,
        )
        st_folium(map_object, width=None, height=600, key="result_map")

