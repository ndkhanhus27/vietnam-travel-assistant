from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings

from pipeline.agents.schemas import (
    EvidenceItem,
    ExecutionPlan,
    ReasonerOutput,
    ToolObservation,
    ValidationResult,
)


# ============================================================
# TRAVEL REASONER
# ============================================================


class TravelReasoner:
    """
    Convert validated agent context into a structured
    answer plan.

    Input:
        - user query
        - ExecutionPlan
        - RAG / Web research evidence
        - specialized ToolObservations
        - ValidationResult

    Output:
        - ReasonerOutput

    Reasoner KHÔNG:
        - execute tools
        - retrieve documents
        - calculate budget itself
        - invent weather/routing data
        - write final prose answer
        - expose/store chain-of-thought

    Output chỉ là structured answer plan.
    """

    def __init__(
        self,
        *,
        max_evidence_chars: int = 1400,
        max_observation_chars: int = 5000,
    ) -> None:

        if not settings.gemini_api_key:

            raise RuntimeError(
                "GEMINI_API_KEY chưa được cấu hình."
            )

        self.client = genai.Client(
            api_key=settings.gemini_api_key
        )

        self.model = (
            settings.gemini_model
        )

        self.max_evidence_chars = (
            max_evidence_chars
        )

        self.max_observation_chars = (
            max_observation_chars
        )

    # ========================================================
    # TEXT
    # ========================================================

    @staticmethod
    def _clean_text(
        value: str | None,
    ) -> str:

        if not value:
            return ""

        return " ".join(
            value.split()
        )

    # ========================================================
    # EVIDENCE CONTEXT
    # ========================================================

    def _serialize_evidence(
        self,
        evidence: list[EvidenceItem],
    ) -> list[dict[str, Any]]:
        """
        Chỉ đưa evidence cần thiết vào context.

        evidence_id là citation/reference contract quan trọng,
        nên luôn giữ nguyên.
        """

        output: list[
            dict[str, Any]
        ] = []

        for item in evidence:

            content = (
                self._clean_text(
                    item.content
                )
            )

            if (
                len(content)
                > self.max_evidence_chars
            ):

                content = (
                    content[
                        :self.max_evidence_chars
                    ]
                    + "..."
                )

            output.append(
                {
                    "evidence_id": (
                        item.evidence_id
                    ),

                    "source_type": (
                        item.source_type.value
                    ),

                    "entity": (
                        item.entity
                    ),

                    "title": (
                        item.title
                    ),

                    "content": (
                        content
                    ),

                    "url": (
                        item.url
                    ),
                }
            )

        return output

    # ========================================================
    # SPECIALIZED TOOL CONTEXT
    # ========================================================

    @staticmethod
    def _sanitize_data(
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Loại metadata quá lớn / ít giá trị cho Reasoner.

        Ví dụ Weather geocoder trả local_names
        hàng chục ngôn ngữ. Reasoner không cần.
        """

        cleaned = dict(
            data
        )

        resolved_location = (
            cleaned.get(
                "resolved_location"
            )
        )

        if isinstance(
            resolved_location,
            dict,
        ):

            resolved_location = dict(
                resolved_location
            )

            resolved_location.pop(
                "local_names",
                None,
            )

            cleaned[
                "resolved_location"
            ] = resolved_location

        return cleaned

    def _serialize_observations(
        self,
        observations: list[
            ToolObservation
        ],
    ) -> list[dict[str, Any]]:
        """
        Tool observations vẫn giữ task_id để Reasoner
        reference specialized data bằng task ID.

        Research evidence đã có channel riêng,
        nên evidence list không lặp lại tại đây.
        """

        output: list[
            dict[str, Any]
        ] = []

        for observation in observations:

            data = (
                self._sanitize_data(
                    observation.data
                )
            )

            serialized_data = (
                json.dumps(
                    data,
                    ensure_ascii=False,
                    default=str,
                )
            )

            if (
                len(serialized_data)
                > self.max_observation_chars
            ):

                serialized_data = (
                    serialized_data[
                        :self.max_observation_chars
                    ]
                    + "..."
                )

            output.append(
                {
                    "task_id": (
                        observation.task_id
                    ),

                    "tool": (
                        observation.tool.value
                    ),

                    "status": (
                        observation.status.value
                    ),

                    "data": (
                        serialized_data
                    ),

                    "error": (
                        observation.error
                    ),
                }
            )

        return output

    # ========================================================
    # VALIDATION CONTEXT
    # ========================================================

    @staticmethod
    def _serialize_validation(
        validation: ValidationResult,
    ) -> dict[str, Any]:

        return {
            "valid": (
                validation.valid
            ),

            "issues": [
                {
                    "code": issue.code,

                    "message": (
                        issue.message
                    ),

                    "task_id": (
                        issue.task_id
                    ),

                    "recoverable": (
                        issue.recoverable
                    ),
                }
                for issue
                in validation.issues
            ],
        }

    # ========================================================
    # PROMPT
    # ========================================================

    def _build_prompt(
        self,
        *,
        query: str,
        plan: ExecutionPlan,
        observations: list[
            ToolObservation
        ],
        research_evidence: list[
            EvidenceItem
        ],
        validation: ValidationResult,
    ) -> str:

        evidence_context = (
            self._serialize_evidence(
                research_evidence
            )
        )

        observation_context = (
            self._serialize_observations(
                observations
            )
        )

        validation_context = (
            self._serialize_validation(
                validation
            )
        )

        context = {
            "user_query": query,

            "intent": (
                plan.intent.value
            ),

            "goal": (
                plan.goal
            ),

            "entities": (
                plan.entities
            ),

            "research_depth": (
                plan.research_depth.value
            ),

            "validation": (
                validation_context
            ),

            "research_evidence": (
                evidence_context
            ),

            "tool_observations": (
                observation_context
            ),
        }

        return f"""
You are the reasoning/planning stage of a Vietnamese travel assistant.

Your task is to create a STRUCTURED ANSWER PLAN.

Do not write the final conversational answer.

Do not expose chain-of-thought or hidden reasoning.

Use only the supplied evidence and tool observations for factual claims.

Rules:

1. Research claims must be grounded in supplied research_evidence.

2. When using a research claim, reference only evidence_id values that
   actually exist in research_evidence.

3. Weather, budget, routing, map, and other specialized tool facts must
   be grounded in tool_observations.

4. When using specialized tool information, reference only task_id values
   that actually exist in tool_observations.

5. Never invent an evidence_id.

6. Never invent a task_id.

7. Never invent weather, prices, costs, routes, opening hours, or other
   factual data not supplied in context.

8. If validation contains failures or unavailable capabilities, describe
   them in limitations instead of guessing missing information.

9. Set degraded=true when validation.valid=false or when important
   requested information is unavailable.

10. Keep sections directly relevant to the user's request.

11. answer_type should normally correspond to the intent, such as:
    FACTUAL_TRAVEL
    RECOMMENDATION
    COMPARISON
    ITINERARY
    WEATHER
    BUDGET

12. points should contain concise factual or recommendation statements
    intended to be expanded later by the Synthesizer.

13. Do not cite an evidence item merely because it exists. Reference it
    only if that section actually uses it.

14. Failed tool observations may be referenced only to explain a
    limitation, not as factual evidence.

INPUT CONTEXT:

{json.dumps(
    context,
    ensure_ascii=False,
    indent=2,
    default=str,
)}
""".strip()

    # ========================================================
    # REFERENCE VALIDATION
    # ========================================================

    @staticmethod
    def _validate_references(
        *,
        output: ReasonerOutput,
        evidence: list[EvidenceItem],
        observations: list[
            ToolObservation
        ],
    ) -> None:
        """
        Deterministic anti-hallucination check.

        Gemini không được tạo evidence_id / task_id mới.
        """

        valid_evidence_ids = {
            item.evidence_id
            for item in evidence
        }

        valid_task_ids = {
            item.task_id
            for item in observations
        }

        referenced_evidence_ids: set[
            str
        ] = set(
            output.used_evidence_ids
        )

        referenced_task_ids: set[
            str
        ] = set(
            output
            .used_observation_task_ids
        )

        for section in output.sections:

            referenced_evidence_ids.update(
                section.evidence_ids
            )

            referenced_task_ids.update(
                section
                .observation_task_ids
            )

        unknown_evidence = (
            referenced_evidence_ids
            - valid_evidence_ids
        )

        if unknown_evidence:

            raise ValueError(
                "Reasoner invented unknown "
                "evidence_id(s): "
                + ", ".join(
                    sorted(
                        unknown_evidence
                    )
                )
            )

        unknown_tasks = (
            referenced_task_ids
            - valid_task_ids
        )

        if unknown_tasks:

            raise ValueError(
                "Reasoner invented unknown "
                "task_id(s): "
                + ", ".join(
                    sorted(
                        unknown_tasks
                    )
                )
            )

    # ========================================================
    # NORMALIZE TOP-LEVEL REFERENCES
    # ========================================================

    @staticmethod
    def _normalize_reference_lists(
        output: ReasonerOutput,
    ) -> ReasonerOutput:
        """
        Đồng bộ top-level used_* IDs với references
        thực tế trong sections.

        Không tin hoàn toàn LLM bookkeeping.
        """

        evidence_ids = list(
            output.used_evidence_ids
        )

        task_ids = list(
            output
            .used_observation_task_ids
        )

        for section in output.sections:

            evidence_ids.extend(
                section.evidence_ids
            )

            task_ids.extend(
                section
                .observation_task_ids
            )

        evidence_ids = list(
            dict.fromkeys(
                evidence_ids
            )
        )

        task_ids = list(
            dict.fromkeys(
                task_ids
            )
        )

        return output.model_copy(
            update={
                "used_evidence_ids": (
                    evidence_ids
                ),

                "used_observation_task_ids": (
                    task_ids
                ),
            }
        )

    # ========================================================
    # PUBLIC
    # ========================================================

    def reason(
        self,
        *,
        query: str,
        plan: ExecutionPlan,
        observations: list[
            ToolObservation
        ],
        research_evidence: list[
            EvidenceItem
        ],
        validation: ValidationResult,
    ) -> ReasonerOutput:

        query = query.strip()

        if not query:

            raise ValueError(
                "query cannot be empty."
            )

        prompt = (
            self._build_prompt(
                query=query,
                plan=plan,
                observations=observations,
                research_evidence=(
                    research_evidence
                ),
                validation=validation,
            )
        )

        # ====================================================
        # JSON SCHEMA
        # ====================================================

        response_schema = (
            ReasonerOutput
            .model_json_schema()
        )

        # ====================================================
        # GEMINI
        # ====================================================

        response = (
            self.client.models
            .generate_content(
                model=self.model,

                contents=prompt,

                config=types.GenerateContentConfig(
                    temperature=0.2,

                    response_mime_type=(
                        "application/json"
                    ),

                    # Send JSON Schema directly so strict
                    # additionalProperties constraints are
                    # preserved at the provider boundary.
                    response_json_schema=(
                        response_schema
                    ),
                ),
            )
        )

        response_text = (
            response.text
        )

        if not response_text:

            raise RuntimeError(
                "Gemini Reasoner returned "
                "no JSON output."
            )

        output = (
            ReasonerOutput
            .model_validate_json(
                response_text
            )
        )

        # ====================================================
        # FORCE DEGRADED WHEN VALIDATION FAILED
        # ====================================================

        if not validation.valid:

            output = output.model_copy(
                update={
                    "degraded": True,
                }
            )

        # ====================================================
        # REFERENCE BOOKKEEPING
        # ====================================================

        output = (
            self
            ._normalize_reference_lists(
                output
            )
        )

        # ====================================================
        # ANTI-HALLUCINATION CHECK
        # ====================================================

        self._validate_references(
            output=output,
            evidence=research_evidence,
            observations=observations,
        )

        return output
