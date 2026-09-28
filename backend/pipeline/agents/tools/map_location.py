from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from pipeline.agents.schemas import (
    GeoPoint,
    MapLocationCandidate,
    MapLocationMode,
    MapLocationRequest,
    MapLocationResult,
    SubTask,
    TaskStatus,
    ToolName,
    ToolObservation,
)
from pipeline.agents.tools.providers import (
    GoongClient,
    GoongProviderError,
)


# ============================================================
# MAP LOCATION TOOL
# ============================================================


class MapLocationTool:
    """
    Geocoding / reverse-geocoding tool.

    Responsibilities:
        - validate SubTask arguments
        - call Goong provider
        - normalize provider JSON
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
            tool=ToolName.MAP_LOCATION,
            status=TaskStatus.FAILED,
            data=payload,
            evidence=[],
            coverage=None,
            error=message,
            source_count=0,
        )

    # ========================================================
    # PROVIDER NORMALIZATION
    # ========================================================

    @staticmethod
    def _optional_text(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

    @classmethod
    def _normalize_candidate(
        cls,
        raw_candidate: Any,
    ) -> MapLocationCandidate | None:
        if not isinstance(raw_candidate, dict):
            return None

        geometry = raw_candidate.get("geometry")

        if not isinstance(geometry, dict):
            return None

        location = geometry.get("location")

        if not isinstance(location, dict):
            return None

        lat = location.get("lat")
        lon = location.get("lng")

        if (
            not isinstance(lat, (int, float))
            or isinstance(lat, bool)
            or not isinstance(lon, (int, float))
            or isinstance(lon, bool)
        ):
            return None

        try:
            return MapLocationCandidate(
                name=cls._optional_text(
                    raw_candidate.get("name")
                ),
                formatted_address=cls._optional_text(
                    raw_candidate.get("formatted_address")
                ),
                place_id=cls._optional_text(
                    raw_candidate.get("place_id")
                ),
                point=GeoPoint(
                    lat=float(lat),
                    lon=float(lon),
                ),
            )
        except ValidationError:
            return None

    @classmethod
    def _normalize_result(
        cls,
        *,
        payload: dict[str, Any],
        request: MapLocationRequest,
    ) -> MapLocationResult:
        raw_candidates = payload.get("results")

        if not isinstance(raw_candidates, list):
            raise GoongProviderError(
                "Goong API returned an unexpected geocode payload."
            )

        candidates: list[MapLocationCandidate] = []

        for raw_candidate in raw_candidates:
            candidate = cls._normalize_candidate(raw_candidate)

            if candidate is None:
                continue

            candidates.append(candidate)

            if len(candidates) >= request.limit:
                break

        return MapLocationResult(
            mode=request.mode,
            query=(
                request.query.strip()
                if request.query is not None
                else None
            ),
            point=request.point,
            candidates=candidates,
        )

    # ========================================================
    # PUBLIC EXECUTION
    # ========================================================

    def execute(
        self,
        task: SubTask,
    ) -> ToolObservation:
        if task.tool != ToolName.MAP_LOCATION:
            return self._failed(
                task_id=task.task_id,
                code="MAP_LOCATION_INVALID_ARGUMENTS",
                message=(
                    "MapLocationTool requires "
                    "tool=map_location."
                ),
            )

        try:
            request = MapLocationRequest.model_validate(
                task.arguments
            )
        except ValidationError as exc:
            return self._failed(
                task_id=task.task_id,
                code="MAP_LOCATION_INVALID_ARGUMENTS",
                message=(
                    "Map location arguments are invalid: "
                    f"{exc}"
                ),
            )

        try:
            if request.mode == MapLocationMode.FORWARD:
                payload = self.client.geocode(
                    request.query or ""
                )
            else:
                point = request.point

                if point is None:
                    return self._failed(
                        task_id=task.task_id,
                        code="MAP_LOCATION_INVALID_ARGUMENTS",
                        message=(
                            "Reverse map location requires "
                            "a point."
                        ),
                    )

                payload = self.client.reverse_geocode(
                    lat=point.lat,
                    lon=point.lon,
                    limit=request.limit,
                )

            result = self._normalize_result(
                payload=payload,
                request=request,
            )
        except GoongProviderError as exc:
            return self._failed(
                task_id=task.task_id,
                code="MAP_LOCATION_PROVIDER_ERROR",
                message=f"Goong request failed: {exc}",
                data={
                    "mode": request.mode.value,
                },
            )
        except Exception as exc:
            return self._failed(
                task_id=task.task_id,
                code="MAP_LOCATION_PROVIDER_ERROR",
                message=(
                    "Goong request failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                data={
                    "mode": request.mode.value,
                },
            )

        if not result.candidates:
            return self._failed(
                task_id=task.task_id,
                code="MAP_LOCATION_NOT_FOUND",
                message="No matching map location was found.",
                data=result.model_dump(mode="json"),
            )

        return ToolObservation(
            task_id=task.task_id,
            tool=ToolName.MAP_LOCATION,
            status=TaskStatus.SUCCESS,
            data=result.model_dump(mode="json"),
            evidence=[],
            coverage=None,
            error=None,
            source_count=len(result.candidates),
        )
