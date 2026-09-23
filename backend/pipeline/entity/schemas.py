from typing import Literal

from pydantic import BaseModel


# ================================================================
# ENTITY TYPE
# ================================================================

EntityType = Literal[
    "country",
    "province",
    "city",
    "town",
    "destination",
    "attraction",
    "heritage",
    "beach",
    "mountain",
    "island",
    "national_park",
    "airport",
    "activity",
    "other",
]


# ================================================================
# ENTITY ROLE
# ================================================================

EntityRole = Literal[
    "primary",
    "mention",
]


# ================================================================
# STRUCTURED OUTPUT ITEM
# ================================================================

class ExtractedEntityCandidate(BaseModel):
    """
    Một entity candidate do AI extract.

    Đây CHƯA phải canonical Entity.

    Canonicalization và Wikidata resolution
    nằm ở Step 3C.
    """

    # Tên entity.
    #
    # Ví dụ:
    # Đồng Hới
    # Quảng Bình
    # Biển Nhật Lệ
    name: str

    # Bắt buộc thuộc enum EntityType.
    entity_type: EntityType

    # primary:
    # entity chính của bài.
    #
    # mention:
    # entity chỉ được đề cập.
    role: EntityRole

    # Surface form thực tế xuất hiện trong text.
    #
    # Nếu không tìm được chính xác:
    # trả "".
    mention_text: str

    # AI extraction confidence.
    #
    # Prompt bắt buộc model trả từ 0.0 đến 1.0.
    #
    # Wikidata verification confidence là chuyện khác.
    confidence: float


# ================================================================
# STRUCTURED OUTPUT ROOT
# ================================================================

class EntityExtractionResult(BaseModel):
    """
    Structured Output root.

    Gemini phải luôn trả:

    {
      "entities": [...]
    }
    """

    entities: list[
        ExtractedEntityCandidate
    ]