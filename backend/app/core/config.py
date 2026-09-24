from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash-lite"

    entity_extractor_version: str = "entity-v1"
    entity_extract_max_chars: int = 24_000

    model_config = SettingsConfigDict(
        env_file=".env",
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


settings = Settings()