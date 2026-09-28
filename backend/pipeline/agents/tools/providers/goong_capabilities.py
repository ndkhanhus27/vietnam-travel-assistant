from __future__ import annotations

from enum import Enum

from pipeline.agents.schemas import (
    TravelMode,
)


class GoongDirectionsVehicle(str, Enum):
    """
    Các token đã được verify trực tiếp với Goong Directions API hiện tại.
    """

    CAR = "car"
    BIKE = "bike"
    TAXI = "taxi"
    TRUCK = "truck"
    HD = "hd"


GOONG_DIRECTIONS_MODE_MAP: dict[
    TravelMode,
    GoongDirectionsVehicle,
] = {
    TravelMode.CAR: GoongDirectionsVehicle.CAR,
    TravelMode.BICYCLE: GoongDirectionsVehicle.BIKE,
    TravelMode.TAXI: GoongDirectionsVehicle.TAXI,
}


def resolve_goong_directions_vehicle(
    mode: TravelMode,
) -> GoongDirectionsVehicle | None:
    return GOONG_DIRECTIONS_MODE_MAP.get(mode)
