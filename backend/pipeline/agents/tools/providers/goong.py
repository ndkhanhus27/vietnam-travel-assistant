from __future__ import annotations

import time
from typing import Any, Iterable

import httpx

from app.core.config import settings


Coordinate = tuple[float, float]


class GoongProviderError(RuntimeError):
    """
    Safe provider-level error.

    Không expose full request URL vì URL chứa api_key.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        retryable: bool = False,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)

        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable
        self.provider_message = provider_message


class GoongClient:
    """
    Low-level Goong REST API V2 client.

    Supported:
        - Autocomplete V2
        - Children ID V2
        - Place Detail V2
        - Forward geocode
        - Reverse geocode
        - Geocode by place_id
        - Geocode Street V2
        - Directions V2
        - Distance Matrix V2
        - Trip V2
        - Static Map Route V1

    Responsibilities:
        - HTTP
        - authentication
        - provider parameter formatting
        - basic input validation
        - transient retry
        - safe errors

    Không:
        - ToolObservation
        - LangGraph
        - routing reasoning
        - itinerary reasoning
        - provider response normalization
        - Redis caching
    """

    _RETRYABLE_STATUS_CODES = {
        429,
        500,
        502,
        503,
        504,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        http_client: httpx.Client | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if (
            http_client is not None
            and client is not None
        ):
            raise ValueError(
                "Use only one of http_client or client."
            )

        self.api_key = (
            api_key
            if api_key is not None
            else settings.goong_api_key
        ).strip()

        if not self.api_key:
            raise GoongProviderError(
                "GOONG_API_KEY chưa được cấu hình.",
                error_code="GOONG_API_KEY_MISSING",
            )

        self.base_url = (
            base_url
            if base_url is not None
            else settings.goong_base_url
        ).rstrip("/")

        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else getattr(
                settings,
                "goong_timeout_seconds",
                15.0,
            )
        )

        self.max_retries = (
            max_retries
            if max_retries is not None
            else getattr(
                settings,
                "goong_max_retries",
                2,
            )
        )

        self.retry_backoff_seconds = (
            retry_backoff_seconds
            if retry_backoff_seconds is not None
            else getattr(
                settings,
                "goong_retry_backoff_seconds",
                0.35,
            )
        )

        if self.max_retries < 0:
            raise ValueError(
                "max_retries must be >= 0."
            )

        if self.retry_backoff_seconds < 0:
            raise ValueError(
                "retry_backoff_seconds must be >= 0."
            )

        injected_client = (
            http_client
            if http_client is not None
            else client
        )

        self._owns_http_client = injected_client is None

        self._http = (
            injected_client
            if injected_client is not None
            else httpx.Client(
                timeout=self.timeout_seconds,
                headers={
                    "Accept": "application/json",
                    "User-Agent": (
                        "VietnamTravelAdvisor/1.0"
                    ),
                },
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                ),
            )
        )

    # ========================================================
    # LIFECYCLE
    # ========================================================

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def __enter__(self) -> GoongClient:
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.close()

    # ========================================================
    # GENERIC HELPERS
    # ========================================================

    @staticmethod
    def _bool(value: bool) -> str:
        return (
            "true"
            if value
            else "false"
        )

    @staticmethod
    def _require_text(
        value: str,
        *,
        name: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                f"{name} cannot be empty."
            )

        return value

    @staticmethod
    def _validate_coordinate(
        *,
        lat: float,
        lon: float,
    ) -> None:
        if not (
            -90.0 <= lat <= 90.0
        ):
            raise ValueError(
                "lat must be between -90 and 90."
            )

        if not (
            -180.0 <= lon <= 180.0
        ):
            raise ValueError(
                "lon must be between -180 and 180."
            )

    @classmethod
    def _coordinate(
        cls,
        point: Coordinate,
    ) -> str:
        lat, lon = point

        cls._validate_coordinate(
            lat=lat,
            lon=lon,
        )

        return f"{lat},{lon}"

    @classmethod
    def _coordinate_list(
        cls,
        points: Iterable[Coordinate],
        *,
        separator: str,
        name: str,
    ) -> str:
        points = list(points)

        if not points:
            raise ValueError(
                f"{name} cannot be empty."
            )

        return separator.join(
            cls._coordinate(point)
            for point in points
        )

    @staticmethod
    def _clean_params(
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value
            in params.items()
            if value is not None
        }

    def _provider_error_message(
        self,
        response: httpx.Response,
    ) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None

        if not isinstance(payload, dict):
            return None

        for key in (
            "error",
            "message",
            "status",
            "detail",
        ):
            value = payload.get(key)

            if (
                isinstance(value, str)
                and value.strip()
            ):
                return value.strip().replace(
                    self.api_key,
                    "[redacted]",
                )

        return None

    # ========================================================
    # RETRY
    # ========================================================

    def _retry_delay(
        self,
        *,
        attempt: int,
        response: httpx.Response | None = None,
    ) -> float:
        if response is not None:
            retry_after = (
                response.headers.get(
                    "Retry-After"
                )
            )

            if retry_after:
                try:
                    value = float(
                        retry_after
                    )

                    if value >= 0:
                        return min(
                            value,
                            5.0,
                        )

                except ValueError:
                    pass

        return min(
            self.retry_backoff_seconds
            * (2 ** attempt),
            3.0,
        )

    # ========================================================
    # HTTP
    # ========================================================

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        url = (
            f"{self.base_url}{path}"
        )

        request_params = (
            self._clean_params(
                {
                    **params,
                    "api_key": self.api_key,
                }
            )
        )

        last_error: Exception | None = None

        for attempt in range(
            self.max_retries + 1
        ):
            response: (
                httpx.Response | None
            ) = None

            try:
                response = self._http.get(
                    url,
                    params=request_params,
                )

            except httpx.TimeoutException as exc:
                last_error = exc

                if (
                    attempt
                    < self.max_retries
                ):
                    time.sleep(
                        self._retry_delay(
                            attempt=attempt
                        )
                    )
                    continue

                raise GoongProviderError(
                    "Goong request timed out.",
                    error_code="GOONG_REQUEST_FAILED",
                    retryable=True,
                ) from exc

            except httpx.RequestError as exc:
                last_error = exc

                if (
                    attempt
                    < self.max_retries
                ):
                    time.sleep(
                        self._retry_delay(
                            attempt=attempt
                        )
                    )
                    continue

                raise GoongProviderError(
                    (
                        "Không thể kết nối "
                        "tới Goong API."
                    ),
                    error_code=(
                        "GOONG_CONNECTION_ERROR"
                    ),
                    retryable=True,
                ) from exc

            if (
                response.status_code
                in self._RETRYABLE_STATUS_CODES
                and attempt
                < self.max_retries
            ):
                time.sleep(
                    self._retry_delay(
                        attempt=attempt,
                        response=response,
                    )
                )
                continue

            if not (
                200
                <= response.status_code
                < 300
            ):
                retryable = (
                    response.status_code
                    in self
                    ._RETRYABLE_STATUS_CODES
                )

                raise GoongProviderError(
                    (
                        "Goong API returned "
                        f"HTTP "
                        f"{response.status_code}."
                    ),
                    status_code=(
                        response.status_code
                    ),
                    error_code="GOONG_HTTP_ERROR",
                    retryable=retryable,
                    provider_message=(
                        self._provider_error_message(
                            response
                        )
                    ),
                )

            try:
                payload = response.json()

            except ValueError as exc:
                raise GoongProviderError(
                    (
                        "Goong API returned "
                        "invalid JSON."
                    ),
                    status_code=(
                        response.status_code
                    ),
                    error_code="GOONG_INVALID_JSON",
                ) from exc

            if not isinstance(
                payload,
                dict,
            ):
                raise GoongProviderError(
                    (
                        "Goong API returned "
                        "an unexpected payload."
                    ),
                    status_code=(
                        response.status_code
                    ),
                    error_code=(
                        "GOONG_INVALID_PAYLOAD"
                    ),
                )

            return payload

        raise GoongProviderError(
            "Goong request failed.",
            error_code="GOONG_REQUEST_FAILED",
            retryable=True,
        ) from last_error

    def _get_bytes(
        self,
        path: str,
        *,
        params: dict[str, Any],
    ) -> tuple[bytes, str | None]:
        url = f"{self.base_url}{path}"
        request_params = self._clean_params(
            {
                **params,
                "api_key": self.api_key,
            }
        )

        try:
            response = self._http.get(
                url,
                params=request_params,
            )
        except httpx.RequestError as exc:
            raise GoongProviderError(
                "Không thể kết nối tới Goong API.",
                error_code="GOONG_CONNECTION_ERROR",
                retryable=True,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise GoongProviderError(
                (
                    "Goong API returned "
                    f"HTTP {response.status_code}."
                ),
                status_code=response.status_code,
                error_code="GOONG_HTTP_ERROR",
                retryable=(
                    response.status_code
                    in self._RETRYABLE_STATUS_CODES
                ),
                provider_message=(
                    self._provider_error_message(
                        response
                    )
                ),
            )

        return (
            response.content,
            response.headers.get("Content-Type"),
        )

    # ========================================================
    # AUTOCOMPLETE V2
    # ========================================================

    def autocomplete(
        self,
        query: str,
        *,
        location: Coordinate | None = None,
        origin: Coordinate | None = None,
        limit: int = 5,
        radius: float | None = None,
        more_compound: bool = True,
        include_deprecated: bool = False,
    ) -> dict[str, Any]:
        """
        Search suggestions.

        location:
            bias khu vực tìm kiếm.

        origin:
            provider có thể trả distance_meters
            từ origin tới suggestion.
        """

        query = self._require_text(
            query,
            name="query",
        )

        if limit < 1:
            raise ValueError(
                "limit must be >= 1."
            )

        if (
            radius is not None
            and radius <= 0
        ):
            raise ValueError(
                "radius must be > 0."
            )

        return self._get(
            "/v2/place/autocomplete",
            params={
                "input": query,

                "location": (
                    None
                    if location is None
                    else self._coordinate(
                        location
                    )
                ),

                "origin": (
                    None
                    if origin is None
                    else self._coordinate(
                        origin
                    )
                ),

                "limit": limit,

                "radius": radius,

                "more_compound": (
                    self._bool(
                        more_compound
                    )
                ),

                (
                    "has_deprecated_"
                    "administrative_unit"
                ): self._bool(
                    include_deprecated
                ),
            },
        )

    # ========================================================
    # CHILDREN ID V2
    # ========================================================

    def children(
        self,
        parent_id: str,
        *,
        include_deprecated: bool = False,
    ) -> dict[str, Any]:
        parent_id = self._require_text(
            parent_id,
            name="parent_id",
        )

        return self._get(
            "/v2/place/children",
            params={
                "parent_id": parent_id,

                (
                    "has_deprecated_"
                    "administrative_unit"
                ): self._bool(
                    include_deprecated
                ),
            },
        )

    def place_children(
        self,
        parent_id: str,
        *,
        include_deprecated: bool = False,
    ) -> dict[str, Any]:
        """Alias matching the public place API terminology."""

        return self.children(
            parent_id,
            include_deprecated=include_deprecated,
        )

    # ========================================================
    # PLACE DETAIL V2
    # ========================================================

    def place_detail(
        self,
        place_id: str,
        *,
        include_deprecated: bool = False,
    ) -> dict[str, Any]:
        place_id = self._require_text(
            place_id,
            name="place_id",
        )

        return self._get(
            "/v2/place/detail",
            params={
                "place_id": place_id,

                (
                    "has_deprecated_"
                    "administrative_unit"
                ): self._bool(
                    include_deprecated
                ),
            },
        )

    # ========================================================
    # FORWARD GEOCODE V2
    # ========================================================

    def geocode(
        self,
        address: str,
        *,
        include_deprecated: bool = False,
    ) -> dict[str, Any]:
        address = self._require_text(
            address,
            name="address",
        )

        return self._get(
            "/v2/geocode",
            params={
                "address": address,

                (
                    "has_deprecated_"
                    "administrative_unit"
                ): self._bool(
                    include_deprecated
                ),
            },
        )

    # ========================================================
    # REVERSE GEOCODE V2
    # ========================================================

    def reverse_geocode(
        self,
        *,
        lat: float,
        lon: float,
        limit: int = 5,
        include_deprecated: bool = False,
        include_vnid: bool = False,
        has_vnid: bool | None = None,
    ) -> dict[str, Any]:
        self._validate_coordinate(
            lat=lat,
            lon=lon,
        )

        if limit < 1:
            raise ValueError(
                "limit must be >= 1."
            )

        resolved_has_vnid = (
            include_vnid
            if has_vnid is None
            else has_vnid
        )

        return self._get(
            "/v2/geocode",
            params={
                "latlng": (
                    f"{lat},{lon}"
                ),

                "limit": limit,

                (
                    "has_deprecated_"
                    "administrative_unit"
                ): self._bool(
                    include_deprecated
                ),

                "has_vnid": (
                    self._bool(
                        resolved_has_vnid
                    )
                ),
            },
        )

    # ========================================================
    # GEOCODE BY PLACE ID
    # ========================================================

    def geocode_place_id(
        self,
        place_id: str,
        *,
        include_deprecated: bool = False,
    ) -> dict[str, Any]:
        """
        Goong Geocode V2 docs liệt kê place_id lookup
        là chức năng thứ ba của /v2/geocode.
        """

        place_id = self._require_text(
            place_id,
            name="place_id",
        )

        return self._get(
            "/v2/geocode",
            params={
                "place_id": place_id,

                (
                    "has_deprecated_"
                    "administrative_unit"
                ): self._bool(
                    include_deprecated
                ),
            },
        )

    # ========================================================
    # GEOCODE STREET V2
    # ========================================================

    def geocode_street(
        self,
        *,
        lat: float,
        lon: float,
        include_deprecated: bool = False,
    ) -> dict[str, Any]:
        self._validate_coordinate(
            lat=lat,
            lon=lon,
        )

        return self._get(
            "/v2/geocode/street",
            params={
                "latlng": (
                    f"{lat},{lon}"
                ),

                (
                    "has_deprecated_"
                    "administrative_unit"
                ): self._bool(
                    include_deprecated
                ),
            },
        )

    # ========================================================
    # DIRECTIONS V2
    # ========================================================

    def directions(
        self,
        *,
        origin: Coordinate | None = None,
        destination: Coordinate | None = None,
        origin_lat: float | None = None,
        origin_lon: float | None = None,
        destination_lat: float | None = None,
        destination_lon: float | None = None,
        vehicle: str = "car",
        alternatives: bool = False,
    ) -> dict[str, Any]:
        """
        Không hard-code provider vehicle enum ở đây.

        RoutingTool phía trên chịu trách nhiệm map
        TravelMode → token Goong đã verify.
        """

        vehicle = self._require_text(
            vehicle,
            name="vehicle",
        ).lower()

        resolved_origin = self._resolve_route_point(
            name="origin",
            point=origin,
            lat=origin_lat,
            lon=origin_lon,
        )
        resolved_destination = self._resolve_route_point(
            name="destination",
            point=destination,
            lat=destination_lat,
            lon=destination_lon,
        )

        return self._get(
            "/v2/direction",
            params={
                "origin": (
                    self._coordinate(
                        resolved_origin
                    )
                ),

                "destination": (
                    self._coordinate(
                        resolved_destination
                    )
                ),

                "vehicle": vehicle,

                "alternatives": (
                    self._bool(
                        alternatives
                    )
                ),
            },
        )

    @classmethod
    def _resolve_route_point(
        cls,
        *,
        name: str,
        point: Coordinate | None,
        lat: float | None,
        lon: float | None,
    ) -> Coordinate:
        has_split_coordinate = (
            lat is not None
            or lon is not None
        )

        if point is not None and has_split_coordinate:
            raise ValueError(
                f"{name} must use either a tuple or lat/lon."
            )

        if point is not None:
            cls._coordinate(point)
            return point

        if lat is None or lon is None:
            raise ValueError(
                f"{name} coordinate is required."
            )

        resolved = (lat, lon)
        cls._coordinate(resolved)
        return resolved

    # ========================================================
    # DISTANCE MATRIX V2
    # ========================================================

    def distance_matrix(
        self,
        *,
        origins: list[Coordinate],
        destinations: list[Coordinate],
        vehicle: str = "car",
    ) -> dict[str, Any]:
        vehicle = self._require_text(
            vehicle,
            name="vehicle",
        ).lower()

        origins_param = (
            self._coordinate_list(
                origins,
                separator="|",
                name="origins",
            )
        )

        destinations_param = (
            self._coordinate_list(
                destinations,
                separator="|",
                name="destinations",
            )
        )

        return self._get(
            "/v2/distancematrix",
            params={
                "origins": origins_param,
                "destinations": (
                    destinations_param
                ),
                "vehicle": vehicle,
            },
        )

    # ========================================================
    # TRIP V2
    # ========================================================

    def trip(
        self,
        *,
        waypoints: list[Coordinate],
        origin: Coordinate | None = None,
        destination: Coordinate | None = None,
        vehicle: str = "car",
        roundtrip: bool = True,
        validate_minimum_points: bool = True,
    ) -> dict[str, Any]:
        """
        Trip optimization.

        Goong docs hiện ghi tổng số tọa độ
        cần ít nhất 10 điểm cho optimized trip.

        Vì vậy:
            - itinerary nhỏ: Distance Matrix
            - itinerary >=10 điểm: Trip có thể phù hợp
        """

        vehicle = self._require_text(
            vehicle,
            name="vehicle",
        ).lower()

        total_points = (
            len(waypoints)
            + (
                1
                if origin is not None
                else 0
            )
            + (
                1
                if destination is not None
                else 0
            )
        )

        if (
            validate_minimum_points
            and total_points < 10
        ):
            raise ValueError(
                (
                    "Goong Trip V2 requires "
                    "at least 10 total "
                    "coordinates according "
                    "to current documentation."
                )
            )

        if not waypoints:
            raise ValueError(
                "waypoints cannot be empty."
            )

        return self._get(
            "/v2/trip",
            params={
                "origin": (
                    None
                    if origin is None
                    else self._coordinate(
                        origin
                    )
                ),

                "destination": (
                    None
                    if destination is None
                    else self._coordinate(
                        destination
                    )
                ),

                "waypoints": (
                    self._coordinate_list(
                        waypoints,
                        separator=";",
                        name="waypoints",
                    )
                ),

                "vehicle": vehicle,

                "roundtrip": (
                    self._bool(
                        roundtrip
                    )
                ),
            },
        )

    # ========================================================
    # STATIC MAP ROUTE V1
    # ========================================================

    def static_map_route(
        self,
        *,
        origin: Coordinate,
        destination: Coordinate,
        vehicle: str = "car",
        width: int = 600,
        height: int = 400,
        route_type: str = "fastest",
        color: str | None = None,
    ) -> tuple[bytes, str | None]:
        """Return static route image bytes without exposing its URL."""

        if not 1 <= width <= 2000:
            raise ValueError(
                "width must be between 1 and 2000."
            )

        if not 1 <= height <= 2000:
            raise ValueError(
                "height must be between 1 and 2000."
            )

        vehicle = self._require_text(
            vehicle,
            name="vehicle",
        ).lower()
        route_type = self._require_text(
            route_type,
            name="route_type",
        ).lower()

        if route_type not in {
            "fastest",
            "shortest",
        }:
            raise ValueError(
                "route_type must be "
                "'fastest' or 'shortest'."
            )

        return self._get_bytes(
            "/staticmap/route",
            params={
                "origin": self._coordinate(origin),
                "destination": self._coordinate(
                    destination
                ),
                "vehicle": vehicle,
                "width": width,
                "height": height,
                "type": route_type,
                "color": color,
            },
        )
