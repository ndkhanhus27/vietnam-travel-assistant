from __future__ import annotations

import logging
import math
from typing import Any

from pydantic import ValidationError

from pipeline.agents.schemas import (
    GeoPoint,
    ResolvedRouteLocation,
    RouteAlternative,
    RouteLeg,
    RouteStep,
    RoutingLocation,
    RoutingRequest,
    RoutingResult,
    SubTask,
    TaskStatus,
    ToolName,
    ToolObservation,
)
from pipeline.agents.tools.providers import (
    GoongClient,
    GoongProviderError,
)
from pipeline.agents.tools.providers.goong_capabilities import (
    resolve_goong_directions_vehicle,
)
from pipeline.agents.tools.utils import normalize_text


logger = logging.getLogger(__name__)


class _RoutingLocationNotFound(RuntimeError):
    def __init__(
        self,
        *,
        side: str,
        query: str,
    ) -> None:
        super().__init__(
            f"No location found for {side}: {query}"
        )
        self.side = side
        self.query = query


class RoutingTool:
    """
    A -> B routing tool.

    Responsibilities:
        - validate SubTask arguments
        - reject unsupported domain modes before provider calls
        - resolve text locations through Goong geocoding
        - call Goong Directions
        - normalize provider JSON into RoutingResult
        - return ToolObservation
    """

    def __init__(
        self,
        client: GoongClient | None = None,
    ) -> None:
        self._client = client

    @property
    def client(self) -> GoongClient:
        if self._client is None:
            self._client = GoongClient()

        return self._client

    # ========================================================
    # FAILED RESULT
    # ========================================================

    @staticmethod
    def _failed(
        *,
        task_id: str,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> ToolObservation:
        payload = dict(data or {})
        payload["error_code"] = code

        return ToolObservation(
            task_id=task_id,
            tool=ToolName.ROUTING,
            status=TaskStatus.FAILED,
            data=payload,
            evidence=[],
            coverage=None,
            error=message,
            source_count=0,
        )

    # ========================================================
    # COMMON NORMALIZATION
    # ========================================================

    @staticmethod
    def _optional_text(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

    @staticmethod
    def _number(
        value: Any,
    ) -> float | None:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return float(value)

        return None

    @classmethod
    def _measure_value(
        cls,
        value: Any,
    ) -> float:
        if isinstance(value, dict):
            value = value.get("value")

        numeric = cls._number(value)
        return numeric if numeric is not None else 0.0

    @classmethod
    def _point_from_provider(
        cls,
        value: Any,
    ) -> GeoPoint | None:
        if not isinstance(value, dict):
            return None

        lat = cls._number(value.get("lat"))
        lon = cls._number(
            value.get(
                "lng",
                value.get("lon"),
            )
        )

        if lat is None or lon is None:
            return None

        try:
            return GeoPoint(
                lat=lat,
                lon=lon,
            )
        except ValidationError:
            return None

    # ========================================================
    # LOCATION RESOLUTION
    # ========================================================

    def _resolve_location_candidates(
        self,
        *,
        side: str,
        location: RoutingLocation,
    ) -> list[ResolvedRouteLocation]:
        if location.point is not None:
            return [ResolvedRouteLocation(point=location.point)]

        query = location.query or ""
        payload = self.client.geocode(query)
        raw_results = payload.get("results")

        if not isinstance(raw_results, list):
            raise GoongProviderError(
                "Goong API returned an unexpected geocode payload.",
                error_code="GOONG_INVALID_PAYLOAD",
            )

        candidates: list[ResolvedRouteLocation] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue

            geometry = raw_result.get("geometry")
            provider_location = (
                geometry.get("location")
                if isinstance(geometry, dict)
                else None
            )
            point = self._point_from_provider(
                provider_location
            )

            if point is None:
                continue

            candidates.append(
                ResolvedRouteLocation(
                    query=query,
                    name=self._optional_text(raw_result.get("name")),
                    formatted_address=self._optional_text(
                        raw_result.get("formatted_address")
                    ),
                    place_id=self._optional_text(raw_result.get("place_id")),
                    point=point,
                )
            )

        if candidates:
            return candidates

        raise _RoutingLocationNotFound(
            side=side,
            query=query,
        )

    @staticmethod
    def _geodesic_distance_meters(first: GeoPoint, second: GeoPoint) -> float:
        earth_radius_meters = 6_371_000.0
        lat1 = math.radians(first.lat)
        lat2 = math.radians(second.lat)
        delta_lat = lat2 - lat1
        delta_lon = math.radians(second.lon - first.lon)
        value = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
        )
        return 2 * earth_radius_meters * math.asin(min(1.0, math.sqrt(value)))

    @classmethod
    def _select_compatible_locations(
        cls,
        origins: list[ResolvedRouteLocation],
        destinations: list[ResolvedRouteLocation],
    ) -> tuple[ResolvedRouteLocation, ResolvedRouteLocation]:
        pairs = [
            (cls._geodesic_distance_meters(origin.point, destination.point), origin, destination)
            for origin in origins
            for destination in destinations
        ]
        non_identical = [item for item in pairs if item[0] >= 50.0]
        distance, origin, destination = min(
            non_identical or pairs,
            key=lambda item: item[0],
        )
        return origin, destination

    @classmethod
    def _plausible_routes(
        cls,
        *,
        origin: ResolvedRouteLocation,
        destination: ResolvedRouteLocation,
        routes: list[RouteAlternative],
    ) -> tuple[list[RouteAlternative], float]:
        straight_distance = cls._geodesic_distance_meters(
            origin.point,
            destination.point,
        )
        maximum_route_distance = max(
            50_000.0,
            straight_distance * 8.0 + 10_000.0,
        )
        plausible = [
            route
            for route in routes
            if route.distance_meters > 0
            and route.duration_seconds > 0
            and route.distance_meters >= straight_distance * 0.75
            and route.distance_meters <= maximum_route_distance
        ]
        return plausible, straight_distance

    @staticmethod
    def _ambiguous_long_distance(
        origin: ResolvedRouteLocation,
        destination: ResolvedRouteLocation,
        straight_distance: float,
    ) -> bool:
        if straight_distance < 300_000:
            return False
        if not origin.query or not destination.query:
            return False
        if not origin.formatted_address or not destination.formatted_address:
            return False

        origin_region = normalize_text(origin.formatted_address.split(",")[-1])
        destination_region = normalize_text(
            destination.formatted_address.split(",")[-1]
        )
        if (
            not origin_region
            or not destination_region
            or origin_region == destination_region
        ):
            return False

        origin_explicit = origin_region in normalize_text(origin.query)
        destination_explicit = destination_region in normalize_text(
            destination.query
        )
        return not origin_explicit and not destination_explicit

    # ========================================================
    # DIRECTIONS NORMALIZATION
    # ========================================================

    @classmethod
    def _normalize_step(
        cls,
        raw_step: Any,
    ) -> RouteStep | None:
        if not isinstance(raw_step, dict):
            return None

        raw_polyline = raw_step.get("polyline")
        polyline = (
            raw_polyline.get("points")
            if isinstance(raw_polyline, dict)
            else None
        )

        return RouteStep(
            instruction=cls._optional_text(
                raw_step.get(
                    "html_instructions",
                    raw_step.get("instruction"),
                )
            ),
            maneuver=cls._optional_text(
                raw_step.get("maneuver")
            ),
            distance_meters=cls._measure_value(
                raw_step.get("distance")
            ),
            duration_seconds=cls._measure_value(
                raw_step.get("duration")
            ),
            start_point=cls._point_from_provider(
                raw_step.get("start_location")
            ),
            end_point=cls._point_from_provider(
                raw_step.get("end_location")
            ),
            polyline=cls._optional_text(polyline),
        )

    @classmethod
    def _normalize_leg(
        cls,
        raw_leg: Any,
    ) -> RouteLeg | None:
        if not isinstance(raw_leg, dict):
            return None

        raw_steps = raw_leg.get("steps")
        steps: list[RouteStep] = []

        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                step = cls._normalize_step(raw_step)

                if step is not None:
                    steps.append(step)

        return RouteLeg(
            distance_meters=cls._measure_value(
                raw_leg.get("distance")
            ),
            duration_seconds=cls._measure_value(
                raw_leg.get("duration")
            ),
            start_address=cls._optional_text(
                raw_leg.get("start_address")
            ),
            end_address=cls._optional_text(
                raw_leg.get("end_address")
            ),
            start_point=cls._point_from_provider(
                raw_leg.get("start_location")
            ),
            end_point=cls._point_from_provider(
                raw_leg.get("end_location")
            ),
            steps=steps,
        )

    @classmethod
    def _normalize_route(
        cls,
        raw_route: Any,
    ) -> RouteAlternative | None:
        if not isinstance(raw_route, dict):
            return None

        raw_legs = raw_route.get("legs")

        if not isinstance(raw_legs, list):
            return None

        legs: list[RouteLeg] = []

        for raw_leg in raw_legs:
            leg = cls._normalize_leg(raw_leg)

            if leg is not None:
                legs.append(leg)

        if not legs:
            return None

        raw_polyline = raw_route.get(
            "overview_polyline"
        )
        polyline = (
            raw_polyline.get("points")
            if isinstance(raw_polyline, dict)
            else None
        )

        return RouteAlternative(
            distance_meters=sum(
                leg.distance_meters
                for leg in legs
            ),
            duration_seconds=sum(
                leg.duration_seconds
                for leg in legs
            ),
            summary=cls._optional_text(
                raw_route.get("summary")
            ),
            polyline=cls._optional_text(polyline),
            legs=legs,
        )

    @classmethod
    def _normalize_routes(
        cls,
        payload: dict[str, Any],
    ) -> list[RouteAlternative]:
        raw_routes = payload.get("routes")

        if not isinstance(raw_routes, list):
            raise GoongProviderError(
                "Goong API returned an unexpected directions payload.",
                error_code="GOONG_INVALID_PAYLOAD",
            )

        routes: list[RouteAlternative] = []

        for raw_route in raw_routes:
            route = cls._normalize_route(raw_route)

            if route is not None:
                routes.append(route)

        return routes

    # ========================================================
    # PUBLIC EXECUTION
    # ========================================================

    def execute(
        self,
        task: SubTask,
    ) -> ToolObservation:
        if task.tool != ToolName.ROUTING:
            return self._failed(
                task_id=task.task_id,
                code="ROUTING_INVALID_ARGUMENTS",
                message=(
                    "RoutingTool requires tool=routing."
                ),
            )

        try:
            request = RoutingRequest.model_validate(
                task.arguments
            )
        except ValidationError as exc:
            return self._failed(
                task_id=task.task_id,
                code="ROUTING_INVALID_ARGUMENTS",
                message=(
                    "Routing arguments are invalid: "
                    f"{exc}"
                ),
            )

        provider_vehicle = (
            resolve_goong_directions_vehicle(
                request.mode
            )
        )

        if provider_vehicle is None:
            return self._failed(
                task_id=task.task_id,
                code="ROUTING_MODE_UNSUPPORTED",
                message=(
                    "Routing mode is not supported by "
                    f"Goong Directions: {request.mode.value}"
                ),
                data={
                    "requested_mode": request.mode.value,
                },
            )

        try:
            origin_candidates = self._resolve_location_candidates(
                side="origin",
                location=request.origin,
            )
            destination_candidates = self._resolve_location_candidates(
                side="destination",
                location=request.destination,
            )
            origin, destination = self._select_compatible_locations(
                origin_candidates,
                destination_candidates,
            )

            payload = self.client.directions(
                origin=(
                    origin.point.lat,
                    origin.point.lon,
                ),
                destination=(
                    destination.point.lat,
                    destination.point.lon,
                ),
                vehicle=provider_vehicle.value,
                alternatives=request.alternatives,
            )
            routes = self._normalize_routes(payload)
        except _RoutingLocationNotFound as exc:
            return self._failed(
                task_id=task.task_id,
                code=(
                    "ROUTING_ORIGIN_NOT_FOUND"
                    if exc.side == "origin"
                    else "ROUTING_DESTINATION_NOT_FOUND"
                ),
                message=str(exc),
                data={
                    "location": exc.side,
                    "query": exc.query,
                    "requested_mode": request.mode.value,
                },
            )
        except GoongProviderError as exc:
            return self._failed(
                task_id=task.task_id,
                code="ROUTING_PROVIDER_ERROR",
                message=f"Goong routing request failed: {exc}",
                data={
                    "requested_mode": request.mode.value,
                    "provider_vehicle": provider_vehicle.value,
                    "provider_error_code": exc.error_code,
                    "provider_status_code": exc.status_code,
                    "provider_message": exc.provider_message,
                },
            )
        except Exception as exc:
            return self._failed(
                task_id=task.task_id,
                code="ROUTING_PROVIDER_ERROR",
                message=(
                    "Routing request failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                data={
                    "requested_mode": request.mode.value,
                    "provider_vehicle": provider_vehicle.value,
                },
            )

        if not routes:
            return self._failed(
                task_id=task.task_id,
                code="ROUTING_NO_ROUTE",
                message="Goong did not return a usable route.",
                data={
                    "requested_mode": request.mode.value,
                    "provider_vehicle": provider_vehicle.value,
                    "origin": origin.model_dump(mode="json"),
                    "destination": destination.model_dump(
                        mode="json"
                    ),
                },
            )

        routes, straight_distance = self._plausible_routes(
            origin=origin,
            destination=destination,
            routes=routes,
        )
        ambiguous_geocoding = self._ambiguous_long_distance(
            origin,
            destination,
            straight_distance,
        )
        if not routes or ambiguous_geocoding:
            logger.warning(
                "Routing sanity validation failed",
                extra={
                    "origin_query": request.origin.query,
                    "destination_query": request.destination.query,
                    "straight_distance_meters": round(straight_distance, 2),
                },
            )
            return self._failed(
                task_id=task.task_id,
                code=(
                    "ROUTING_AMBIGUOUS_GEOCODING"
                    if ambiguous_geocoding
                    else "ROUTING_IMPLAUSIBLE"
                ),
                message=(
                    "Routing locations resolved to incompatible regions."
                    if ambiguous_geocoding
                    else "Routing provider returned a geographically implausible route."
                ),
                data={
                    "requested_mode": request.mode.value,
                    "provider_vehicle": provider_vehicle.value,
                    "origin": origin.model_dump(mode="json"),
                    "destination": destination.model_dump(mode="json"),
                    "straight_distance_meters": round(straight_distance, 2),
                },
            )

        result = RoutingResult(
            requested_mode=request.mode,
            provider_vehicle=provider_vehicle.value,
            origin=origin,
            destination=destination,
            routes=routes,
        )

        return ToolObservation(
            task_id=task.task_id,
            tool=ToolName.ROUTING,
            status=TaskStatus.SUCCESS,
            data=result.model_dump(mode="json"),
            evidence=[],
            coverage=None,
            error=None,
            source_count=len(routes),
        )
