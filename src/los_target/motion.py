"""UAS/target motion models and the delayed-engagement intercept solver."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, pi, radians, sin, sqrt
from typing import Literal, Optional, Protocol

from .geometry import NorthEast


class UASDelayMotion(Protocol):
    """Motion interface for UAS movement during the engagement delay."""

    speed_mps: float

    def position_at(self, time_s: float) -> NorthEast:
        ...

    def bearing_at(self, time_s: float) -> float:
        ...


@dataclass(frozen=True)
class StraightTrack:
    """Straight, constant-speed ground track."""

    position: NorthEast
    speed_mps: float
    bearing_deg: float

    @property
    def velocity(self) -> NorthEast:
        bearing_rad = radians(self.bearing_deg)
        return NorthEast(
            north_m=self.speed_mps * cos(bearing_rad),
            east_m=self.speed_mps * sin(bearing_rad),
        )

    def position_at(self, time_s: float) -> NorthEast:
        return self.position + self.velocity * time_s

    def bearing_at(self, time_s: float) -> float:
        del time_s
        return self.bearing_deg % 360.0


@dataclass(frozen=True)
class CircularLoiter:
    """Constant-speed circular loiter in the local North/East frame."""

    center: NorthEast
    radius_m: float
    speed_mps: float
    turn_direction: Literal["CW", "CCW"]
    initial_position: NorthEast

    def validate(self, radial_tolerance_m: float) -> None:
        if self.radius_m <= 0.0:
            raise ValueError("LOITER_RADIUS_M must be positive.")
        if self.speed_mps <= 0.0:
            raise ValueError("UAS_SPEED_MPS must be positive.")
        if self.turn_direction not in ("CW", "CCW"):
            raise ValueError("LOITER_TURN_DIRECTION must be 'CW' or 'CCW'.")
        if radial_tolerance_m < 0.0:
            raise ValueError("LOITER_POSITION_TOLERANCE_M must be non-negative.")

        radial_distance_m = (self.initial_position - self.center).magnitude()
        radial_error_m = abs(radial_distance_m - self.radius_m)
        if radial_error_m > radial_tolerance_m:
            raise ValueError(
                "UAS initial position is not on the configured loiter circle. "
                f"Configured radius: {self.radius_m:.1f} m; "
                f"measured radial distance: {radial_distance_m:.1f} m; "
                f"error: {radial_error_m:.1f} m. "
                "Either correct the coordinates/radius, increase the tolerance, "
                "or use LOITER_POSITION_MODE = 'RADIAL_BEARING_FROM_CENTER'."
            )

    @property
    def turn_sign(self) -> float:
        return 1.0 if self.turn_direction == "CW" else -1.0

    @property
    def initial_phase_rad(self) -> float:
        """
        Angle from the loiter center to the UAS.

        theta=0 is north of center; theta increases clockwise toward east.
        """
        radial = self.initial_position - self.center
        return atan2(radial.east_m, radial.north_m)

    @property
    def angular_rate_rad_s(self) -> float:
        return self.turn_sign * self.speed_mps / self.radius_m

    @property
    def period_s(self) -> float:
        return 2.0 * pi * self.radius_m / self.speed_mps

    def phase_at(self, time_s: float) -> float:
        return self.initial_phase_rad + self.angular_rate_rad_s * time_s

    def position_at(self, time_s: float) -> NorthEast:
        theta = self.phase_at(time_s)
        return NorthEast(
            north_m=self.center.north_m + self.radius_m * cos(theta),
            east_m=self.center.east_m + self.radius_m * sin(theta),
        )

    def bearing_at(self, time_s: float) -> float:
        """Tangent ground track at time_s, clockwise from north."""
        radial_bearing_deg = degrees(self.phase_at(time_s)) % 360.0
        tangent_offset_deg = 90.0 if self.turn_direction == "CW" else -90.0
        return (radial_bearing_deg + tangent_offset_deg) % 360.0


@dataclass(frozen=True)
class InterceptSolution:
    """Computed timing and future target waypoint."""

    engagement_delay_s: float
    time_after_engagement_s: float
    total_time_from_now_s: float
    uas_position_at_engagement: NorthEast
    target_position_at_engagement: NorthEast
    waypoint: NorthEast
    uas_tangent_bearing_at_engagement_deg: float
    command_bearing_deg: float
    distance_after_engagement_m: float


def offset_from_center(
    center: NorthEast,
    distance_m: float,
    bearing_deg: float,
) -> NorthEast:
    """Return the point distance_m away from center along bearing_deg."""
    bearing_rad = radians(bearing_deg)
    return NorthEast(
        north_m=center.north_m + distance_m * cos(bearing_rad),
        east_m=center.east_m + distance_m * sin(bearing_rad),
    )


def bearing_from_to_deg(start: NorthEast, end: NorthEast) -> float:
    """Navigation bearing clockwise from north."""
    delta = end - start
    return degrees(atan2(delta.east_m, delta.north_m)) % 360.0


def solve_positive_intercept_time(
    relative_position: NorthEast,
    target_velocity: NorthEast,
    uas_speed_mps: float,
) -> Optional[float]:
    """
    Find the earliest t > 0 satisfying:

        ||relative_position + target_velocity * t|| = uas_speed_mps * t

    The UAS speed is constrained but its post-delay direction is free.
    """
    a = target_velocity.dot(target_velocity) - uas_speed_mps**2
    b = 2.0 * relative_position.dot(target_velocity)
    c = relative_position.dot(relative_position)

    epsilon = 1e-9
    candidate_times: list[float] = []

    if abs(a) < epsilon:
        if abs(b) < epsilon:
            return None
        time_s = -c / b
        if time_s > epsilon:
            candidate_times.append(time_s)
    else:
        discriminant = b**2 - 4.0 * a * c
        if discriminant < -epsilon:
            return None

        root = sqrt(max(discriminant, 0.0))
        for time_s in (
            (-b - root) / (2.0 * a),
            (-b + root) / (2.0 * a),
        ):
            if time_s > epsilon:
                candidate_times.append(time_s)

    return min(candidate_times) if candidate_times else None


def calculate_waypoint(
    uas_delay_motion: UASDelayMotion,
    target: StraightTrack,
    engagement_delay_s: float,
) -> Optional[InterceptSolution]:
    """
    Advance both systems through the delay, then solve the fixed-speed
    waypoint intercept from the predicted delay-end state.
    """
    if engagement_delay_s < 0.0:
        raise ValueError("ENGAGEMENT_DELAY_S must be non-negative.")
    if uas_delay_motion.speed_mps <= 0.0:
        raise ValueError("UAS_SPEED_MPS must be positive.")
    if target.speed_mps < 0.0:
        raise ValueError("TARGET_SPEED_MPS must be non-negative.")

    uas_engagement = uas_delay_motion.position_at(engagement_delay_s)
    target_engagement = target.position_at(engagement_delay_s)

    time_after_engagement_s = solve_positive_intercept_time(
        relative_position=target_engagement - uas_engagement,
        target_velocity=target.velocity,
        uas_speed_mps=uas_delay_motion.speed_mps,
    )
    if time_after_engagement_s is None:
        return None

    waypoint = target_engagement + target.velocity * time_after_engagement_s

    return InterceptSolution(
        engagement_delay_s=engagement_delay_s,
        time_after_engagement_s=time_after_engagement_s,
        total_time_from_now_s=engagement_delay_s + time_after_engagement_s,
        uas_position_at_engagement=uas_engagement,
        target_position_at_engagement=target_engagement,
        waypoint=waypoint,
        uas_tangent_bearing_at_engagement_deg=(
            uas_delay_motion.bearing_at(engagement_delay_s)
        ),
        command_bearing_deg=bearing_from_to_deg(uas_engagement, waypoint),
        distance_after_engagement_m=(
            uas_delay_motion.speed_mps * time_after_engagement_s
        ),
    )
