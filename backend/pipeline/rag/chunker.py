from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.rag.bge_tokenizer import BgeM3Tokenizer


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str
    token_count: int


def normalize_text(
    value: str,
) -> str:
    value = value or ""
    value = value.replace("\r\n", "\n")
    value = value.replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)

    return value.strip()


def split_paragraphs(
    content: str,
) -> list[str]:
    content = normalize_text(content)

    if not content:
        return []

    paragraphs = re.split(
        r"\n\s*\n",
        content,
    )

    return [
        paragraph.strip()
        for paragraph in paragraphs
        if paragraph.strip()
    ]


def split_large_text(
    *,
    text: str,
    tokenizer: BgeM3Tokenizer,
    max_tokens: int,
    overlap: int,
) -> list[str]:
    """
    Hard split theo token thật.

    Chỉ dùng khi một paragraph riêng lẻ
    đã lớn hơn chunk_size.
    """

    token_ids = tokenizer.encode(text)

    if len(token_ids) <= max_tokens:
        return [text]

    result: list[str] = []

    start = 0

    while start < len(token_ids):
        end = min(
            start + max_tokens,
            len(token_ids),
        )

        part_ids = token_ids[start:end]
        part = tokenizer.decode(part_ids)

        if part:
            result.append(part)

        if end >= len(token_ids):
            break

        start = max(
            end - overlap,
            start + 1,
        )

    return result


def get_overlap_text(
    *,
    text: str,
    tokenizer: BgeM3Tokenizer,
    overlap: int,
) -> str:
    if overlap <= 0:
        return ""

    token_ids = tokenizer.encode(text)

    if not token_ids:
        return ""

    return tokenizer.decode(token_ids[-overlap:])


def chunk_document(
    *,
    content: str,
    tokenizer: BgeM3Tokenizer,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size phải > 0")

    if overlap < 0:
        raise ValueError("overlap phải >= 0")

    if overlap >= chunk_size:
        raise ValueError("overlap phải nhỏ hơn chunk_size")

    paragraphs = split_paragraphs(content)

    if not paragraphs:
        return []

    # ============================================================
    # Paragraph -> units <= chunk_size
    # ============================================================

    units: list[str] = []

    for paragraph in paragraphs:
        paragraph_tokens = tokenizer.count(paragraph)

        if paragraph_tokens <= chunk_size:
            units.append(paragraph)
        else:
            units.extend(
                split_large_text(
                    text=paragraph,
                    tokenizer=tokenizer,
                    max_tokens=chunk_size,
                    overlap=overlap,
                )
            )

    # ============================================================
    # Merge units
    # ============================================================

    raw_chunks: list[str] = []

    current_parts: list[str] = []

    for unit in units:
        if not current_parts:
            current_parts.append(unit)
            continue

        candidate_text = "\n\n".join(
            [
                *current_parts,
                unit,
            ]
        )

        candidate_tokens = tokenizer.count(candidate_text)

        if candidate_tokens <= chunk_size:
            current_parts.append(unit)
            continue

        # Flush current chunk.
        current_text = "\n\n".join(current_parts)
        raw_chunks.append(current_text)

        overlap_text = get_overlap_text(
            text=current_text,
            tokenizer=tokenizer,
            overlap=overlap,
        )

        current_parts = []

        if overlap_text:
            current_parts.append(overlap_text)

        # Kiểm tra overlap + unit có quá limit không.
        candidate_text = "\n\n".join(
            [
                *current_parts,
                unit,
            ]
        )

        if tokenizer.count(candidate_text) <= chunk_size:
            current_parts.append(unit)

        else:
            # Unit bản thân đã được split trước,
            # trường hợp này chủ yếu do overlap.
            if current_parts:
                raw_chunks.append("\n\n".join(current_parts))

            current_parts = [unit]

    if current_parts:
        raw_chunks.append("\n\n".join(current_parts))

    # ============================================================
    # Final result
    # ============================================================

    result: list[TextChunk] = []

    for raw_text in raw_chunks:
        text = normalize_text(raw_text)

        if not text:
            continue

        token_count = tokenizer.count(text)

        result.append(
            TextChunk(
                chunk_index=len(result),
                content=text,
                token_count=token_count,
            )
        )

    return result
