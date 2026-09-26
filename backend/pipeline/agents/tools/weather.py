from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from pipeline.agents.schemas import (
    TaskStatus,
    ToolName,
    ToolObservation,
    WeatherMode,
    WeatherRequest,
    WEATHER_MAX_FORECAST_OFFSET_DAYS,
)


# ============================================================
# WEATHER TOOL
# ============================================================


class WeatherTool:
    """
    OpenWeather Free adapter.

    Provider flow:

        location
            -> Geocoding API
            -> Current Weather API or 5 Day / 3 Hour Forecast API
            -> deterministic daily aggregation
            -> ToolObservation

    Historical weather is intentionally unsupported because the free
    OpenWeather endpoints used here do not provide historical data.
    """

    def __init__(self) -> None:
        if not settings.openweather_api_key:
            raise RuntimeError(
                "OPENWEATHER_API_KEY chưa được cấu hình."
            )

        self.base_url = settings.openweather_base_url.rstrip("/")

        if not self.base_url.startswith(("http://", "https://")):
            raise RuntimeError(
                "OPENWEATHER_BASE_URL phải bắt đầu "
                "bằng http:// hoặc https://."
            )

        self.api_key = settings.openweather_api_key
        self.units = settings.openweather_units
        self.language = settings.openweather_language
        self.country = settings.openweather_geocode_country
        self.timeout = settings.openweather_timeout_seconds

    # ========================================================
    # FAILED RESULT
    # ========================================================

    @staticmethod
    def _failed(
        *,
        task_id: str,
        message: str,
        code: str,
        data: dict[str, Any] | None = None,
    ) -> ToolObservation:
        payload = dict(data or {})
        payload["error_code"] = code

        return ToolObservation(
            task_id=task_id,
            tool=ToolName.WEATHER,
            status=TaskStatus.FAILED,
            data=payload,
            evidence=[],
            coverage=None,
            error=message,
            source_count=0,
        )

    @staticmethod
    def _request_error_message(exc: Exception) -> str:
        """Format provider errors without exposing the API key in URLs."""

        if isinstance(exc, httpx.HTTPStatusError):
            return (
                f"{type(exc).__name__}: HTTP "
                f"{exc.response.status_code}"
            )

        if isinstance(exc, httpx.RequestError):
            return type(exc).__name__

        return f"{type(exc).__name__}: {exc}"

    # ========================================================
    # GEOCODING
    # ========================================================

    def _geocode(
        self,
        location: str,
    ) -> dict[str, Any] | None:
        """Resolve a location name to coordinates."""

        query = location.strip()

        if not query:
            return None

        if self.country and "," not in query:
            query = f"{query},{self.country}"

        response = httpx.get(
            f"{self.base_url}/geo/1.0/direct",
            params={
                "q": query,
                "limit": 1,
                "appid": self.api_key,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        results = response.json()

        if not results:
            return None

        place = results[0]

        return {
            "name": place.get("name"),
            "lat": float(place["lat"]),
            "lon": float(place["lon"]),
            "country": place.get("country"),
            "state": place.get("state"),
            "local_names": place.get("local_names") or {},
        }

    # ========================================================
    # RANGE VALIDATION
    # ========================================================

    @staticmethod
    def _validate_offsets(
        request: WeatherRequest,
    ) -> tuple[bool, str | None, str | None]:
        start = request.start_offset_days
        end = request.end_offset_days

        if start > end:
            return (
                False,
                "WEATHER_INVALID_RANGE",
                (
                    "Weather start offset không được lớn hơn "
                    "end offset."
                ),
            )

        if start < 0 < end:
            return (
                False,
                "WEATHER_MIXED_RANGE_UNSUPPORTED",
                (
                    "Weather range không được vừa historical "
                    "vừa forecast."
                ),
            )

        history_modes = {
            WeatherMode.RECENT_HISTORY,
            WeatherMode.RECENT_HISTORY_RANGE,
        }

        if (
            request.mode in history_modes
            or start < 0
            or end < 0
        ):
            return (
                False,
                "WEATHER_HISTORY_UNSUPPORTED",
                (
                    "OpenWeather Free hiện không hỗ trợ "
                    "recent weather history."
                ),
            )

        if (
            start > WEATHER_MAX_FORECAST_OFFSET_DAYS
            or end > WEATHER_MAX_FORECAST_OFFSET_DAYS
        ):
            return (
                False,
                "WEATHER_FORECAST_OUT_OF_RANGE",
                (
                    "OpenWeather Free forecast hiện chỉ hỗ trợ "
                    "an toàn từ hôm nay đến +"
                    f"{WEATHER_MAX_FORECAST_OFFSET_DAYS} ngày."
                ),
            )

        return True, None, None

    # ========================================================
    # OPENWEATHER FREE ENDPOINTS
    # ========================================================

    def _get_current(
        self,
        *,
        lat: float,
        lon: float,
    ) -> dict[str, Any]:
        response = httpx.get(
            f"{self.base_url}/data/2.5/weather",
            params={
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": self.units,
                "lang": self.language,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _get_forecast(
        self,
        *,
        lat: float,
        lon: float,
    ) -> dict[str, Any]:
        response = httpx.get(
            f"{self.base_url}/data/2.5/forecast",
            params={
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": self.units,
                "lang": self.language,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ========================================================
    # NORMALIZATION HELPERS
    # ========================================================

    @staticmethod
    def _weather_description(
        payload: dict[str, Any],
    ) -> str | None:
        weather = payload.get("weather") or []

        if not weather or not isinstance(weather[0], dict):
            return None

        value = weather[0].get("description")
        return str(value) if value is not None else None

    @staticmethod
    def _numeric_values(
        payloads: list[dict[str, Any]],
        *path: str,
    ) -> list[float]:
        values: list[float] = []

        for payload in payloads:
            value: Any = payload

            for key in path:
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(key)

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))

        return values

    @staticmethod
    def _average(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    @staticmethod
    def _minimum(values: list[float]) -> float | None:
        return min(values) if values else None

    @staticmethod
    def _maximum(values: list[float]) -> float | None:
        return max(values) if values else None

    @staticmethod
    def _timezone_offset_seconds(
        payload: dict[str, Any],
    ) -> int:
        city = payload.get("city") or {}
        raw_offset = city.get("timezone", 0)

        try:
            return int(raw_offset)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _destination_today(
        timezone_offset_seconds: int,
    ) -> date:
        destination_now = (
            datetime.now(timezone.utc)
            + timedelta(seconds=timezone_offset_seconds)
        )
        return destination_now.date()

    @staticmethod
    def _forecast_point_date(
        point: dict[str, Any],
        timezone_offset_seconds: int,
    ) -> date | None:
        raw_timestamp = point.get("dt")

        if isinstance(raw_timestamp, (int, float)):
            local_time = (
                datetime.fromtimestamp(
                    raw_timestamp,
                    tz=timezone.utc,
                )
                + timedelta(seconds=timezone_offset_seconds)
            )
            return local_time.date()

        raw_text = point.get("dt_txt")

        if not raw_text:
            return None

        try:
            utc_time = datetime.strptime(
                str(raw_text),
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        return (
            utc_time
            + timedelta(seconds=timezone_offset_seconds)
        ).date()

    # ========================================================
    # CURRENT NORMALIZATION
    # ========================================================

    def _normalize_current(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        main = payload.get("main") or {}
        wind = payload.get("wind") or {}
        clouds = payload.get("clouds") or {}
        rain = payload.get("rain") or {}

        return {
            "kind": "current",
            "temperature_c": main.get("temp"),
            "feels_like_c": main.get("feels_like"),
            "temp_min_c": main.get("temp_min"),
            "temp_max_c": main.get("temp_max"),
            "humidity_percent": main.get("humidity"),
            "pressure_hpa": main.get("pressure"),
            "wind_speed": wind.get("speed"),
            "clouds_percent": clouds.get("all"),
            "uvi": None,
            "description": self._weather_description(payload),
            "rain_1h_mm": rain.get("1h"),
        }

    # ========================================================
    # 3-HOUR FORECAST -> DAILY AGGREGATION
    # ========================================================

    def _aggregate_day(
        self,
        *,
        points: list[dict[str, Any]],
        target_date: date,
        offset: int,
    ) -> dict[str, Any]:
        temperatures = self._numeric_values(points, "main", "temp")
        min_temperatures = self._numeric_values(
            points,
            "main",
            "temp_min",
        )
        max_temperatures = self._numeric_values(
            points,
            "main",
            "temp_max",
        )
        feels_like = self._numeric_values(
            points,
            "main",
            "feels_like",
        )
        humidity = self._numeric_values(points, "main", "humidity")
        pressure = self._numeric_values(points, "main", "pressure")
        wind_speed = self._numeric_values(points, "wind", "speed")
        cloud_cover = self._numeric_values(points, "clouds", "all")
        precipitation_probability = self._numeric_values(points, "pop")
        rain = self._numeric_values(points, "rain", "3h")

        descriptions = [
            description
            for point in points
            if (
                description := self._weather_description(point)
            )
        ]
        unique_descriptions = list(dict.fromkeys(descriptions))
        primary_description = (
            Counter(descriptions).most_common(1)[0][0]
            if descriptions
            else None
        )

        return {
            "kind": "forecast",
            "offset_days": offset,
            "date": target_date.isoformat(),
            "temp_min_c": self._minimum(
                min_temperatures or temperatures
            ),
            "temp_max_c": self._maximum(
                max_temperatures or temperatures
            ),
            "temp_day_c": self._average(temperatures),
            "feels_like_day_c": self._average(feels_like),
            "humidity_percent": self._average(humidity),
            "pressure_hpa": self._average(pressure),
            "wind_speed": self._maximum(wind_speed),
            "clouds_percent": self._average(cloud_cover),
            "uvi": None,
            "precipitation_probability": self._maximum(
                precipitation_probability
            ),
            "rain_mm": round(sum(rain), 2) if rain else 0.0,
            "description": primary_description,
            "descriptions": unique_descriptions,
            "forecast_points": len(points),
        }

    def _normalize_daily_forecast(
        self,
        *,
        payload: dict[str, Any],
        start_offset: int,
        end_offset: int,
    ) -> list[dict[str, Any]]:
        raw_points = payload.get("list") or []
        timezone_offset = self._timezone_offset_seconds(payload)
        today = self._destination_today(timezone_offset)
        points_by_date: dict[date, list[dict[str, Any]]] = {}

        for raw_point in raw_points:
            if not isinstance(raw_point, dict):
                continue

            point_date = self._forecast_point_date(
                raw_point,
                timezone_offset,
            )

            if point_date is None:
                continue

            points_by_date.setdefault(point_date, []).append(raw_point)

        output: list[dict[str, Any]] = []

        for offset in range(start_offset, end_offset + 1):
            target_date = today + timedelta(days=offset)
            points = points_by_date.get(target_date, [])

            if not points:
                continue

            output.append(
                self._aggregate_day(
                    points=points,
                    target_date=target_date,
                    offset=offset,
                )
            )

        return output

    # ========================================================
    # PUBLIC EXECUTION
    # ========================================================

    def execute(
        self,
        *,
        task_id: str,
        request: WeatherRequest,
    ) -> ToolObservation:
        location = request.location.strip()

        if not location:
            return self._failed(
                task_id=task_id,
                code="WEATHER_LOCATION_MISSING",
                message="Weather query thiếu location.",
            )

        valid, error_code, error_message = self._validate_offsets(request)

        if not valid:
            return self._failed(
                task_id=task_id,
                code=error_code or "WEATHER_INVALID_REQUEST",
                message=error_message or "Weather request không hợp lệ.",
                data={
                    "location": location,
                    "mode": request.mode.value,
                    "start_offset_days": request.start_offset_days,
                    "end_offset_days": request.end_offset_days,
                },
            )

        try:
            place = self._geocode(location)
        except Exception as exc:
            return self._failed(
                task_id=task_id,
                code="WEATHER_GEOCODE_ERROR",
                message=(
                    "Không thể geocode location: "
                    f"{self._request_error_message(exc)}"
                ),
                data={"location": location},
            )

        if place is None:
            return self._failed(
                task_id=task_id,
                code="WEATHER_LOCATION_NOT_FOUND",
                message=f"Không tìm thấy location: {location}",
                data={"location": location},
            )

        lat = float(place["lat"])
        lon = float(place["lon"])
        start = request.start_offset_days
        end = request.end_offset_days
        current_only = (
            request.mode == WeatherMode.CURRENT
            and start == 0
            and end == 0
        )

        try:
            if current_only:
                payload = self._get_current(lat=lat, lon=lon)
                weather_data = [self._normalize_current(payload)]
                endpoint = "/data/2.5/weather"
            else:
                payload = self._get_forecast(lat=lat, lon=lon)
                weather_data = self._normalize_daily_forecast(
                    payload=payload,
                    start_offset=start,
                    end_offset=end,
                )
                endpoint = "/data/2.5/forecast"
        except Exception as exc:
            return self._failed(
                task_id=task_id,
                code="WEATHER_PROVIDER_ERROR",
                message=(
                    "OpenWeather request failed: "
                    f"{self._request_error_message(exc)}"
                ),
                data={
                    "location": location,
                    "lat": lat,
                    "lon": lon,
                },
            )

        if not weather_data:
            return self._failed(
                task_id=task_id,
                code="WEATHER_DATA_EMPTY",
                message=(
                    "Weather provider không trả dữ liệu cho khoảng "
                    "thời gian được yêu cầu."
                ),
                data={
                    "location": location,
                    "start_offset_days": start,
                    "end_offset_days": end,
                },
            )

        return ToolObservation(
            task_id=task_id,
            tool=ToolName.WEATHER,
            status=TaskStatus.SUCCESS,
            data={
                "provider": "openweather",
                "provider_plan": "free",
                "provider_endpoint": endpoint,
                "requested_location": location,
                "resolved_location": place,
                "mode": request.mode.value,
                "time_expression": request.time_expression,
                "start_offset_days": start,
                "end_offset_days": end,
                "weather": weather_data,
            },
            evidence=[],
            coverage=None,
            error=None,
            source_count=1,
        )
