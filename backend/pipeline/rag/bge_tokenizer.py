from __future__ import annotations

from transformers import AutoTokenizer


MODEL_NAME = "BAAI/bge-m3"


class BgeM3Tokenizer:
    def __init__(self) -> None:
        self.tokenizer = (
            AutoTokenizer.from_pretrained(
                MODEL_NAME
            )
        )

    def encode(
        self,
        text: str,
    ) -> list[int]:
        return self.tokenizer.encode(
            text,
            add_special_tokens=False,
        )

    def decode(
        self,
        token_ids: list[int],
    ) -> str:
        return self.tokenizer.decode(
            token_ids,
            skip_special_tokens=True,
        ).strip()

    def count(
        self,
        text: str,
    ) -> int:
        return len(
            self.encode(text)
        )