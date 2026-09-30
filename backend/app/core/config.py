from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str

    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, gt=0)
    refresh_token_expire_days: int = Field(default=30, gt=0)
    google_client_id: str = ""
    cors_origins: str = "http://localhost:5173"

    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    rate_limit_enabled: bool = True
    rate_limit_chat_requests: int = Field(default=10, gt=0)
    rate_limit_chat_window_seconds: int = Field(default=60, gt=0)
    rate_limit_auth_requests: int = Field(default=10, gt=0)
    rate_limit_auth_window_seconds: int = Field(default=60, gt=0)
    cache_default_ttl_seconds: int = Field(default=300, gt=0)
    cache_weather_ttl_seconds: int = Field(default=600, gt=0)
    cache_geocode_ttl_seconds: int = Field(default=86_400, gt=0)

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash-lite"

    entity_extractor_version: str = "entity-v1"
    entity_extract_max_chars: int = 24_000

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # ============================================================
    # RAG
    # ============================================================

    rag_embedding_model: str = "BAAI/bge-m3"

    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 64

    rag_embedding_batch_size: int = 8

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "travel_chunks"

    rag_vector_size: int = 1024
    rag_retrieve_limit: int = 12
    rag_context_chunks: int = 6
    rag_max_chunks_per_document: int = 2
    # ============================================================
    # HYBRID RETRIEVAL
    # ============================================================

    rag_dense_candidates: int = 20
    rag_bm25_candidates: int = 20

    rag_hybrid_limit: int = 12

    rag_rrf_k: int = 60

    rag_rrf_dense_weight: float = 1.0
    rag_rrf_bm25_weight: float = 1.0
    rag_rrf_entity_weight: float = 0.5
    
    # ============================================================
    # RERANKER
    # ============================================================
    rag_rerank_enabled: bool = True
    rag_reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    rag_rerank_candidates: int = 20
    rag_rerank_limit: int = 6
    rag_reranker_batch_size: int = 8
    rag_reranker_max_length: int = 512
    
    # ============================================================
    # WEB RESEARCH
    # ============================================================

    tavily_api_key: str = ""

    web_search_max_results: int = 5
    web_search_depth: Literal[
        "basic",
        "advanced",
        "fast",
        "ultra-fast",
    ] = "advanced"
    web_search_chunks_per_source: int = 2   

    # ============================================================
    # OPENWEATHER
    # ============================================================

    openweather_api_key: str = ""
    openweather_base_url: str = "https://api.openweathermap.org"
    openweather_units: str = "metric"
    openweather_language: str = "vi"
    openweather_geocode_country: str = "VN"
    openweather_timeout_seconds: float = 15.0

    # ============================================================
    # GOONG
    # ============================================================

    goong_api_key: str = ""
    goong_base_url: str = "https://rsapi.goong.io"
    goong_timeout_seconds: float = 15.0
    goong_max_retries: int = 2
    goong_retry_backoff_seconds: float = 0.35

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_cors(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",")]
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must not contain '*'")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


settings = Settings()
