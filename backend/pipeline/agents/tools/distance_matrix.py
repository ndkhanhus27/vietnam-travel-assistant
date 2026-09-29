from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from pipeline.agents.schemas import (
    DistanceMatrixElement,
    DistanceMatrixRequest,
    DistanceMatrixResult,
    DistanceMatrixRow,
    GeoPoint,
    ResolvedRouteLocation,
    RoutingLocation,
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
    resolve_goong_distance_matrix_vehicle,
)


class _MatrixLocationNotFound(RuntimeError):
    def __init__(
        self,
        *,
        side: str,
        index: int,
        query: str,
    ) -> None:
        super().__init__(
            f"No location found for {side}[{index}]: {query}"
        )
        self.side = side
        self.index = index
        self.query = query


class DistanceMatrixTool:
    """Resolve locations and return an index-addressable matrix."""

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
            tool=ToolName.DISTANCE_MATRIX,
            status=TaskStatus.FAILED,
            data=payload,
            evidence=[],
            coverage=None,
            error=message,
            source_count=0,
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

    @staticmethod
    def _number(value: Any) -> float | None:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return float(value)

        return None

    @classmethod
    def _point_from_provider(
        cls,
        value: Any,
    ) -> GeoPoint | None:
        if not isinstance(value, dict):
            return None

        lat = cls._number(value.get("lat"))
        lon = cls._number(
            value.get("lng", value.get("lon"))
        )

        if lat is None or lon is None:
            return None

        try:
            return GeoPoint(lat=lat, lon=lon)
        except ValidationError:
            return None

    @staticmethod
    def _location_key(
        location: RoutingLocation,
    ) -> tuple[str, str | float, float | None]:
        if location.point is not None:
            return (
                "point",
                location.point.lat,
                location.point.lon,
            )

        query = " ".join(
            (location.query or "").split()
        )
        return ("query", query.casefold(), None)

    def _resolve_location(
        self,
        *,
        side: str,
        index: int,
        location: RoutingLocation,
    ) -> ResolvedRouteLocation:
        if location.point is not None:
            return ResolvedRouteLocation(point=location.point)

        query = location.query or ""
        payload = self.client.geocode(query)
        raw_results = payload.get("results")

        if not isinstance(raw_results, list):
            raise GoongProviderError(
                "Goong API returned an unexpected geocode payload.",
                error_code="GOONG_INVALID_PAYLOAD",
            )

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

            return ResolvedRouteLocation(
                query=query,
                name=self._optional_text(
                    raw_result.get("name")
                ),
                formatted_address=self._optional_text(
                    raw_result.get("formatted_address")
                ),
                place_id=self._optional_text(
                    raw_result.get("place_id")
                ),
                point=point,
            )

        raise _MatrixLocationNotFound(
            side=side,
            index=index,
            query=query,
        )

    def _resolve_locations(
        self,
        *,
        origins: list[RoutingLocation],
        destinations: list[RoutingLocation],
    ) -> tuple[
        list[ResolvedRouteLocation],
        list[ResolvedRouteLocation],
    ]:
        cache: dict[
            tuple[str, str | float, float | None],
            ResolvedRouteLocation,
        ] = {}

        def resolve_axis(
            side: str,
            locations: list[RoutingLocation],
        ) -> list[ResolvedRouteLocation]:
            resolved: list[ResolvedRouteLocation] = []

            for index, location in enumerate(locations):
                key = self._location_key(location)
                item = cache.get(key)

                if item is None:
                    item = self._resolve_location(
                        side=side,
                        index=index,
                        location=location,
                    )
                    cache[key] = item

                resolved.append(item)

            return resolved

        return (
            resolve_axis("origin", origins),
            resolve_axis("destination", destinations),
        )

    @classmethod
    def _measure_value(
        cls,
        value: Any,
    ) -> int | None:
        if not isinstance(value, dict):
            return None

        numeric = cls._number(value.get("value"))

        if numeric is None or numeric < 0:
            return None

        return int(round(numeric))

    @classmethod
    def _normalize_rows(
        cls,
        *,
        payload: dict[str, Any],
        origin_count: int,
        destination_count: int,
    ) -> list[DistanceMatrixRow]:
        raw_rows = payload.get("rows")

        if (
            not isinstance(raw_rows, list)
            or len(raw_rows) != origin_count
        ):
            raise GoongProviderError(
                "Goong returned an unexpected matrix row count.",
                error_code="GOONG_INVALID_PAYLOAD",
            )

        rows: list[DistanceMatrixRow] = []

        for origin_index, raw_row in enumerate(raw_rows):
            if not isinstance(raw_row, dict):
                raise GoongProviderError(
                    "Goong returned an invalid matrix row.",
                    error_code="GOONG_INVALID_PAYLOAD",
                )

            raw_elements = raw_row.get("elements")

            if (
                not isinstance(raw_elements, list)
                or len(raw_elements) != destination_count
            ):
                raise GoongProviderError(
                    "Goong returned an unexpected matrix column count.",
                    error_code="GOONG_INVALID_PAYLOAD",
                )

            elements: list[DistanceMatrixElement] = []

            for destination_index, raw_element in enumerate(
                raw_elements
            ):
                if not isinstance(raw_element, dict):
                    raise GoongProviderError(
                        "Goong returned an invalid matrix element.",
                        error_code="GOONG_INVALID_PAYLOAD",
                    )

                raw_status = raw_element.get("status")
                status = (
                    str(raw_status).strip().upper()
                    if raw_status is not None
                    else "UNKNOWN"
                )
                status = status or "UNKNOWN"
                distance = cls._measure_value(
                    raw_element.get("distance")
                )
                duration = cls._measure_value(
                    raw_element.get("duration")
                )

                if status == "OK" and (
                    distance is None
                    or duration is None
                ):
                    raise GoongProviderError(
                        "Goong returned an OK matrix element without "
                        "distance or duration.",
                        error_code="GOONG_INVALID_PAYLOAD",
                    )

                elements.append(
                    DistanceMatrixElement(
                        origin_index=origin_index,
                        destination_index=destination_index,
                        status=status,
                        distance_meters=distance,
                        duration_seconds=duration,
                    )
                )

            rows.append(
                DistanceMatrixRow(
                    origin_index=origin_index,
                    elements=elements,
                )
            )

        return rows

    def execute(
        self,
        task: SubTask,
    ) -> ToolObservation:
        if task.tool != ToolName.DISTANCE_MATRIX:
            return self._failed(
                task_id=task.task_id,
                code="DISTANCE_MATRIX_INVALID_ARGUMENTS",
                message=(
                    "DistanceMatrixTool requires "
                    "tool=distance_matrix."
                ),
            )

        try:
            request = DistanceMatrixRequest.model_validate(
                task.arguments
            )
        except ValidationError as exc:
            return self._failed(
                task_id=task.task_id,
                code="DISTANCE_MATRIX_INVALID_ARGUMENTS",
                message=(
                    "Distance matrix arguments are invalid: "
                    f"{exc}"
                ),
            )

        provider_vehicle = (
            resolve_goong_distance_matrix_vehicle(
                request.mode
            )
        )

        if provider_vehicle is None:
            return self._failed(
                task_id=task.task_id,
                code="DISTANCE_MATRIX_MODE_UNSUPPORTED",
                message=(
                    "Distance matrix mode is not supported by "
                    "the production Goong mapping: "
                    f"{request.mode.value}"
                ),
                data={
                    "requested_mode": request.mode.value,
                },
            )

        try:
            origins, destinations = self._resolve_locations(
                origins=request.origins,
                destinations=request.destinations,
            )
            payload = self.client.distance_matrix(
                origins=[
                    (item.point.lat, item.point.lon)
                    for item in origins
                ],
                destinations=[
                    (item.point.lat, item.point.lon)
                    for item in destinations
                ],
                vehicle=provider_vehicle.value,
            )
            rows = self._normalize_rows(
                payload=payload,
                origin_count=len(origins),
                destination_count=len(destinations),
            )
        except _MatrixLocationNotFound as exc:
            return self._failed(
                task_id=task.task_id,
                code="DISTANCE_MATRIX_LOCATION_NOT_FOUND",
                message=str(exc),
                data={
                    "location": exc.side,
                    "location_index": exc.index,
                    "query": exc.query,
                    "requested_mode": request.mode.value,
                },
            )
        except GoongProviderError as exc:
            return self._failed(
                task_id=task.task_id,
                code="DISTANCE_MATRIX_PROVIDER_ERROR",
                message=(
                    "Goong distance matrix request failed: "
                    f"{exc}"
                ),
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
                code="DISTANCE_MATRIX_PROVIDER_ERROR",
                message=(
                    "Distance matrix request failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                data={
                    "requested_mode": request.mode.value,
                    "provider_vehicle": provider_vehicle.value,
                },
            )

        result = DistanceMatrixResult(
            requested_mode=request.mode,
            provider_vehicle=provider_vehicle.value,
            origins=origins,
            destinations=destinations,
            rows=rows,
        )
        source_count = sum(
            len(row.elements)
            for row in result.rows
        )

        return ToolObservation(
            task_id=task.task_id,
            tool=ToolName.DISTANCE_MATRIX,
            status=TaskStatus.SUCCESS,
            data=result.model_dump(mode="json"),
            evidence=[],
            coverage=None,
            error=None,
            source_count=source_count,
        )
