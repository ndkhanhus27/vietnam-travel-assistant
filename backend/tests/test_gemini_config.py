from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from google.genai import types

from app.core.config import Settings
from pipeline.agents.llm_runtime import GeminiRuntime


MODEL = "gemini-3.5-flash-lite"
OLD_MODEL = "gemini-2.5-flash-lite"
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


def load_settings(**extra_env: str) -> Settings:
    environment = {
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
        "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters",
        **extra_env,
    }
    with patch.dict(os.environ, environment, clear=True):
        return Settings(_env_file=None)


class FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class FakeClient:
    def __init__(self) -> None:
        self.models = FakeModels()


class GeminiConfigurationTest(unittest.TestCase):
    def test_default_model_is_current(self) -> None:
        self.assertEqual(load_settings().gemini_model, MODEL)

    def test_environment_overrides_default_model(self) -> None:
        configured = load_settings(GEMINI_MODEL="gemini-test-override")
        self.assertEqual(configured.gemini_model, "gemini-test-override")

    def test_runtime_passes_model_name_unchanged(self) -> None:
        client = FakeClient()
        runtime = GeminiRuntime(client=client, max_attempts=1)

        runtime.generate_content(
            model=MODEL,
            contents="ping",
            config=types.GenerateContentConfig(temperature=0),
        )

        self.assertEqual(client.models.calls[0]["model"], MODEL)

    def test_production_sources_do_not_reference_old_model(self) -> None:
        paths = [
            BACKEND_DIR / "app",
            BACKEND_DIR / "pipeline",
            BACKEND_DIR / ".env.example",
            REPO_DIR / "deploy" / ".env.production.example",
        ]
        files = [
            path
            for root in paths
            for path in (
                root.rglob("*.py") if root.is_dir() else [root]
            )
        ]

        for path in files:
            self.assertNotIn(
                OLD_MODEL,
                path.read_text(encoding="utf-8"),
                str(path),
            )


if __name__ == "__main__":
    unittest.main()
