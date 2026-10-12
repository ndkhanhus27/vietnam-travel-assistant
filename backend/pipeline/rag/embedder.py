from __future__ import annotations

from typing import Sequence

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from app.core.config import settings
from pipeline.rag.model_cache import get_model


class BgeM3Embedder:
    """
    Dense embedding bằng BAAI/bge-m3.

    Output:
        1024 dimensions

    Dùng cùng model cho:
        - document chunks
        - user queries
    """

    def __init__(self) -> None:
        if torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        def load_model():
            print(f"[embedding] model={settings.rag_embedding_model}")
            print(f"[embedding] device={self.device}")
            return SentenceTransformer(settings.rag_embedding_model, device=self.device)

        resource = get_model(("embedding", settings.rag_embedding_model, self.device), load_model)
        self.model = resource.model
        self._inference_lock = resource.inference_lock

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        if not texts:
            return np.empty(
                (0, settings.rag_vector_size),
                dtype=np.float32,
            )

        if batch_size is None:
            batch_size = settings.rag_embedding_batch_size

        with self._inference_lock:
            embeddings = self.model.encode(
                list(texts),
                batch_size=batch_size,
                show_progress_bar=show_progress_bar,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )

        embeddings = np.asarray(
            embeddings,
            dtype=np.float32,
        )

        if embeddings.ndim != 2:
            raise RuntimeError(
                "Embedding output phải là "
                "matrix 2 chiều."
            )

        if embeddings.shape[1] != settings.rag_vector_size:
            raise RuntimeError(
                "Sai vector dimension: "
                f"{embeddings.shape[1]} "
                "!= "
                f"{settings.rag_vector_size}"
            )

        return embeddings

    def encode_query(
        self,
        query: str,
    ) -> list[float]:
        query = query.strip()

        if not query:
            raise ValueError("Query không được rỗng.")

        vectors = self.encode(
            [query],
            batch_size=1,
        )

        return vectors[0].astype(float).tolist()
