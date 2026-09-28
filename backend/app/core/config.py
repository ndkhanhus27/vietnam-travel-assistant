from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str

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
    
   


settings = Settings()
