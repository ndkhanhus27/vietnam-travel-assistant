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


class GoongDistanceMatrixVehicle(str, Enum):
    """
    Distance Matrix tokens verified for the production mapping.

    This capability remains separate from Directions because the
    provider may support different vehicle sets per endpoint.
    """

    CAR = "car"
    BIKE = "bike"


GOONG_DISTANCE_MATRIX_MODE_MAP: dict[
    TravelMode,
    GoongDistanceMatrixVehicle,
] = {
    TravelMode.CAR: GoongDistanceMatrixVehicle.CAR,
    TravelMode.BICYCLE: GoongDistanceMatrixVehicle.BIKE,
}


def resolve_goong_distance_matrix_vehicle(
    mode: TravelMode,
) -> GoongDistanceMatrixVehicle | None:
    return GOONG_DISTANCE_MATRIX_MODE_MAP.get(mode)
