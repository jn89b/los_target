"""WGS84 lat/lon and local North/East meter-frame primitives."""

from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS, Transformer


@dataclass(frozen=True)
class LatLon:
    """WGS84 geographic position in decimal degrees."""

    lat_deg: float
    lon_deg: float

    def validate(self) -> None:
        if not -90.0 <= self.lat_deg <= 90.0:
            raise ValueError(f"Latitude out of range: {self.lat_deg}")
        if not -180.0 <= self.lon_deg <= 180.0:
            raise ValueError(f"Longitude out of range: {self.lon_deg}")


@dataclass(frozen=True)
class NorthEast:
    """Position or vector in a local North/East metric frame, meters."""

    north_m: float
    east_m: float

    def __add__(self, other: "NorthEast") -> "NorthEast":
        return NorthEast(
            north_m=self.north_m + other.north_m,
            east_m=self.east_m + other.east_m,
        )

    def __sub__(self, other: "NorthEast") -> "NorthEast":
        return NorthEast(
            north_m=self.north_m - other.north_m,
            east_m=self.east_m - other.east_m,
        )

    def __mul__(self, scalar: float) -> "NorthEast":
        return NorthEast(
            north_m=self.north_m * scalar,
            east_m=self.east_m * scalar,
        )

    def dot(self, other: "NorthEast") -> float:
        return self.north_m * other.north_m + self.east_m * other.east_m

    def magnitude(self) -> float:
        return (self.dot(self)) ** 0.5


@dataclass(frozen=True)
class LocalFrame:
    """Local azimuthal-equidistant North/East meter frame."""

    origin: LatLon
    forward: Transformer
    inverse: Transformer

    @classmethod
    def centered_at(cls, origin: LatLon) -> "LocalFrame":
        origin.validate()

        local_crs = CRS.from_proj4(
            f"+proj=aeqd +lat_0={origin.lat_deg} +lon_0={origin.lon_deg} "
            "+datum=WGS84 +units=m +no_defs"
        )

        return cls(
            origin=origin,
            forward=Transformer.from_crs(
                "EPSG:4326", local_crs, always_xy=True
            ),
            inverse=Transformer.from_crs(
                local_crs, "EPSG:4326", always_xy=True
            ),
        )

    def to_local(self, point: LatLon) -> NorthEast:
        point.validate()
        east_m, north_m = self.forward.transform(point.lon_deg, point.lat_deg)
        return NorthEast(north_m=north_m, east_m=east_m)

    def to_latlon(self, point: NorthEast) -> LatLon:
        lon_deg, lat_deg = self.inverse.transform(point.east_m, point.north_m)
        return LatLon(lat_deg=lat_deg, lon_deg=lon_deg)


def average_latlon(points: list[LatLon]) -> LatLon:
    """Practical regional origin; inputs should not cross the ±180° meridian."""
    if not points:
        raise ValueError("At least one point is required for a local frame.")
    return LatLon(
        lat_deg=sum(point.lat_deg for point in points) / len(points),
        lon_deg=sum(point.lon_deg for point in points) / len(points),
    )
