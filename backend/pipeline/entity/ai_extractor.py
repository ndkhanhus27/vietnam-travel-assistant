import asyncio

from google import genai

from app.core.config import settings

from pipeline.entity.normalizer import (
    merge_candidates,
)

from pipeline.entity.prompts import (
    ENTITY_EXTRACTION_INSTRUCTIONS,
)

from pipeline.entity.schemas import (
    EntityExtractionResult,
    ExtractedEntityCandidate,
)

from pipeline.entity.text_windows import (
    split_for_entity_extraction,
)


class AIEntityExtractor:
    """
    Gemini entity candidate extractor.

    Nhiệm vụ:

        Document
            ↓
        Gemini Structured Output
            ↓
        Pydantic
            ↓
        deduplicate
            ↓
        Entity candidates

    Không:
        - resolve Wikidata
        - insert canonical Entity
        - tạo Neo4j node
    """

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY chưa được cấu hình trong .env"
            )

        self.model = (
            settings.gemini_model
        )

        self.max_chars = (
            settings.entity_extract_max_chars
        )

        self.client = genai.Client(
            api_key=(
                settings.gemini_api_key
            )
        )

    # ============================================================
    # ONE WINDOW - SYNC
    # ============================================================

    def _extract_window_sync(
        self,
        *,
        title: str,
        content: str,
        window_index: int,
        window_count: int,
    ) -> EntityExtractionResult:
        """
        Gọi Gemini cho một temporary extraction window.
        """

        user_input = (
            "TIÊU ĐỀ BÀI VIẾT:\n"
            f"{title}\n\n"

            "WINDOW:\n"
            f"{window_index}/{window_count}\n\n"

            "NỘI DUNG:\n"
            f"{content}"
        )

        interaction = (
            self.client
            .interactions
            .create(
                model=self.model,

                input=user_input,

                system_instruction=(
                    ENTITY_EXTRACTION_INSTRUCTIONS
                ),

                response_format={
                    "type": "text",

                    "mime_type": (
                        "application/json"
                    ),

                    "schema": (
                        EntityExtractionResult
                        .model_json_schema()
                    ),
                },

                store=False,
            )
        )

        output_text = getattr(
            interaction,
            "output_text",
            None,
        )

        if not output_text:
            raise RuntimeError(
                "Gemini không trả output_text"
            )

        try:
            parsed = (
                EntityExtractionResult
                .model_validate_json(
                    output_text
                )
            )

        except Exception as exc:
            raise RuntimeError(
                "Gemini Structured Output "
                "không validate được.\n\n"
                f"Raw output:\n"
                f"{output_text[:3000]}"
            ) from exc

        return parsed

    # ============================================================
    # ONE WINDOW - ASYNC
    # ============================================================

    async def _extract_window(
        self,
        *,
        title: str,
        content: str,
        window_index: int,
        window_count: int,
    ) -> EntityExtractionResult:
        """
        Interactions client hiện đang gọi sync.

        Chạy bằng asyncio.to_thread()
        để không block async DB pipeline.
        """

        return await asyncio.to_thread(
            self._extract_window_sync,

            title=title,
            content=content,
            window_index=window_index,
            window_count=window_count,
        )

    # ============================================================
    # WHOLE DOCUMENT
    # ============================================================

    async def extract(
        self,
        *,
        title: str,
        content: str,
    ) -> list[
        ExtractedEntityCandidate
    ]:
        """
        Extract toàn document.

        Document nhỏ:
            1 window

        Document lớn:
            nhiều windows
                ↓
            merge
                ↓
            deduplicate
        """

        windows = (
            split_for_entity_extraction(
                content,
                max_chars=self.max_chars,
            )
        )

        all_candidates: list[
            ExtractedEntityCandidate
        ] = []

        window_count = len(
            windows
        )

        for index, window in enumerate(
            windows,
            start=1,
        ):
            result = (
                await self._extract_window(
                    title=title,
                    content=window,
                    window_index=index,
                    window_count=(
                        window_count
                    ),
                )
            )

            all_candidates.extend(
                result.entities
            )

        return merge_candidates(
            all_candidates
        )