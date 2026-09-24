from __future__ import annotations

from typing import Sequence

import numpy as np
import torch
from sentence_transformers import (
    SentenceTransformer,
)

from app.core.config import settings


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

        print(
            f"[embedding] model="
            f"{settings.rag_embedding_model}"
        )

        print(
            f"[embedding] device="
            f"{self.device}"
        )

        self.model = SentenceTransformer(
            settings.rag_embedding_model,
            device=self.device,
        )

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:

        if not texts:
            return np.empty(
                (
                    0,
                    settings.rag_vector_size,
                ),
                dtype=np.float32,
            )

        if batch_size is None:
            batch_size = (
                settings
                .rag_embedding_batch_size
            )

        embeddings = self.model.encode(
            list(texts),

            batch_size=batch_size,

            show_progress_bar=(
                show_progress_bar
            ),

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

        if (
            embeddings.shape[1]
            != settings.rag_vector_size
        ):
            raise RuntimeError(
                "Sai vector dimension: "
                f"{embeddings.shape[1]} "
                f"!= "
                f"{settings.rag_vector_size}"
            )

        return embeddings

    def encode_query(
        self,
        query: str,
    ) -> list[float]:

        query = query.strip()

        if not query:
            raise ValueError(
                "Query không được rỗng."
            )

        vectors = self.encode(
            [query],
            batch_size=1,
        )

        return (
            vectors[0]
            .astype(float)
            .tolist()
        )