from __future__ import annotations

import logging
import random
import time
from collections.abc import Collection
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings


logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset(
    {
        429,
        500,
        502,
        503,
        504,
    }
)


class GeminiRuntime:
    """Shared Gemini execution boundary with bounded transient retries."""

    def __init__(
        self,
        *,
        client: genai.Client | None = None,
        api_key: str | None = None,
        max_attempts: int = 3,
        base_delay_seconds: float = 1.0,
        max_jitter_seconds: float = 0.5,
        retryable_status_codes: (
            Collection[int] | None
        ) = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(
                "max_attempts must be at least 1."
            )

        if base_delay_seconds < 0:
            raise ValueError(
                "base_delay_seconds cannot be negative."
            )

        if max_jitter_seconds < 0:
            raise ValueError(
                "max_jitter_seconds cannot be negative."
            )

        if client is None:
            resolved_api_key = (
                api_key
                if api_key is not None
                else settings.gemini_api_key
            )

            if not resolved_api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY is not configured."
                )

            client = genai.Client(
                api_key=resolved_api_key
            )

        self.client = client
        self.max_attempts = max_attempts
        self.base_delay_seconds = (
            base_delay_seconds
        )
        self.max_jitter_seconds = (
            max_jitter_seconds
        )
        self.retryable_status_codes = frozenset(
            retryable_status_codes
            if retryable_status_codes is not None
            else RETRYABLE_STATUS_CODES
        )

    @staticmethod
    def _status_code(exc: Exception) -> int | None:
        for attribute in (
            "status_code",
            "code",
        ):
            value = getattr(exc, attribute, None)

            if isinstance(value, int):
                return value

        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)

        if isinstance(value, int):
            return value

        return None

    def _is_retryable(self, exc: Exception) -> bool:
        return (
            self._status_code(exc)
            in self.retryable_status_codes
        )

    def _retry_delay(
        self,
        *,
        failed_attempt: int,
    ) -> float:
        return (
            self.base_delay_seconds
            * (2 ** (failed_attempt - 1))
            + random.uniform(
                0.0,
                self.max_jitter_seconds,
            )
        )

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: types.GenerateContentConfig,
        max_attempts: int | None = None,
    ) -> types.GenerateContentResponse:
        attempts = (
            self.max_attempts
            if max_attempts is None
            else max_attempts
        )

        if attempts < 1:
            raise ValueError(
                "max_attempts must be at least 1."
            )

        for attempt in range(1, attempts + 1):
            try:
                return self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                status_code = self._status_code(exc)

                if (
                    not self._is_retryable(exc)
                    or attempt == attempts
                ):
                    raise

                delay_seconds = self._retry_delay(
                    failed_attempt=attempt
                )
                logger.warning(
                    (
                        "Gemini transient failure "
                        "status=%s attempt=%s/%s; "
                        "retrying in %.2fs"
                    ),
                    status_code,
                    attempt,
                    attempts,
                    delay_seconds,
                )
                time.sleep(delay_seconds)

        raise RuntimeError(
            "Gemini retry loop ended without a response."
        )
