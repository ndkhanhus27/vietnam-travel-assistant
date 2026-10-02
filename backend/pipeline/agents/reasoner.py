from __future__ import annotations

import json
import math
import re
from typing import Any

from google.genai import types

from app.core.config import settings
from pipeline.agents.context import ConversationContext

from pipeline.agents.llm_runtime import (
    GeminiRuntime,
)

from pipeline.agents.schemas import (
    EvidenceItem,
    ExecutionPlan,
    Intent,
    ReasonerOutput,
    ReasonerPoint,
    ReasonerSection,
    TaskStatus,
    ToolName,
    ToolObservation,
    ValidationResult,
)
from pipeline.agents.tools.utils import format_tool_data_for_presentation


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

    _SPECIALIZED_TOOLS = frozenset(
        {
            ToolName.WEATHER,
            ToolName.MAP_LOCATION,
            ToolName.ROUTING,
            ToolName.BUDGET,
        }
    )

    def __init__(
        self,
        *,
        max_evidence_chars: int = 2200,
        max_observation_chars: int = 5000,
        llm_runtime: GeminiRuntime | None = None,
    ) -> None:

        self.llm_runtime = (
            llm_runtime
            if llm_runtime is not None
            else GeminiRuntime()
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

                    "source_quality_rank": item.metadata.get(
                        "source_quality_rank",
                        3,
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

        return format_tool_data_for_presentation(cleaned)

    def _serialize_observations(
        self,
        observations: list[
            ToolObservation
        ],
    ) -> list[dict[str, Any]]:
        """
        Tool observations vẫn giữ task_id để Reasoner
        reference specialized data bằng task ID.

        RAG / Web đã có evidence channel riêng nên không được
        đưa vào observation_task_ids.
        """

        output: list[
            dict[str, Any]
        ] = []

        for observation in observations:

            if (
                observation.tool
                not in self._SPECIALIZED_TOOLS
            ):
                continue

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
        conversation_context: ConversationContext | None = None,
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

            "constraints": [
                item.model_dump(mode="json")
                for item in plan.constraints
            ],

            "research_depth": (
                plan.research_depth.value
            ),

            "response_modifier": (
                plan.response_modifier.value
                if plan.response_modifier is not None
                else None
            ),

            "active_task": (
                None
                if conversation_context is None
                or conversation_context.active_task is None
                else {
                    "query": conversation_context.active_task.query,
                    "intent": conversation_context.active_task.intent.value,
                    "goal": conversation_context.active_task.goal,
                    "entities": conversation_context.active_task.entities,
                    "previous_answer": conversation_context.active_task.previous_answer,
                }
            ),

            "subtasks": [
                {
                    "task_id": (
                        task.task_id
                    ),

                    "description": (
                        task.description
                    ),

                    "tool": (
                        task.tool.value
                    ),

                    "required": (
                        task.required
                    ),
                }
                for task in plan.subtasks
            ],

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

12. Points should be compact structured content units, but must preserve
    enough grounded detail for the Synthesizer to produce a useful
    answer. Do not compress useful evidence into overly terse one-line
    summaries.

13. Do not cite an evidence item merely because it exists. Reference it
    only if that section actually uses it.

14. Failed tool observations may be referenced only to explain a
    limitation, not as factual evidence.

15. Every required subtask in the execution plan must be addressed in
    the answer plan unless its tool failed or the required information
    is unavailable.

16. Do not substitute generic destination background information for a
    requested subtask.

17. Each section purpose must state which user need or required subtask
    that section addresses.

18. EXPAND means more grounded detail about the SAME active task. Expand
    the places or points already in previous_answer and do not introduce
    unrelated tourism topics.

19. CONDENSE means preserving the key factual content of previous_answer
    in a much shorter form, without introducing new subject matter.

20. ADD_OPTIONS should prefer supported options not already present in
    previous_answer. If evidence cannot support new options, state the
    limitation instead of repeating or inventing items.

21. When multiple Web or RAG sources support the same ordinary factual or
    recommendation claim, prefer the source with the higher
    source_quality_rank. Social sources remain usable for trends or community
    sentiment, but should not displace stronger sources for equivalent facts.

For recommendation, comparison, itinerary, and travel-planning queries:

- Create enough points to cover the important dimensions of the user's
  request.

- Choose the number of useful points according to the ANSWER DEPTH
  POLICY and the amount of grounded evidence available.

- Prefer specific, actionable information over generic statements.

- For attraction recommendations, explain why a place may be relevant,
  not merely list place names.

- For broad RECOMMENDATION queries asking what to visit, where to go,
  or what to do, choose the number of distinct recommendation points
  according to the ANSWER DEPTH POLICY and available grounded evidence.

- Avoid splitting one idea into artificial filler points.

- Prioritize diversity of experience when supported by evidence, such
  as scenery, outdoor activity, city-center activity, food, cafe, or
  night activity.

- Each recommendation point should identify a place or activity and why
  it is worth considering.

- Group related places or ideas when useful.

- When weather or other constraints materially affect recommendations,
  connect those constraints to the travel advice.

- Do not add detail when the evidence does not support it.

- For a broad "where should I go" request, recommend visitable places or
  relevant activities. Do not drift into accommodation, hotels, MICE, golf,
  generic destination history, or tourism-industry commentary unless the
  user asked for those topics.
- Do not select an evidence item whose primary subject is accommodation or
  lodging for a broad place/activity recommendation, even if it mentions the
  requested destination.

- Weather-aware advice must stay probabilistic. A non-zero rain probability
  does not justify saying outdoor plans are guaranteed to be convenient;
  suggest a proportionate rain-safe fallback when supported and useful.

INTENT-AWARE ANSWER CONTRACT:

- GENERAL: concise conversational response; do not inherit travel context.
- FACTUAL_TRAVEL: answer the fact directly, then add only supported context.
- WEATHER: concise conditions, important rounded values, and a practical but
  cautious travel implication.
- ROUTING: route, distance, duration, and a supported practical note.
- CURRENT_INFO: answer the current question directly with fresh citations.
- BUDGET: structured arithmetic, assumptions, known values, and unknowns.
- RECOMMENDATION: several supported options when available and why each fits.
- COMPARISON: preserve the requested subjects and compare meaningful criteria.
- ITINERARY: preserve the complete requested day count.
- OUT_OF_SCOPE: concise boundary and a useful supported alternative.

GROUNDING GRANULARITY RULES:

- Each point must contain only the evidence IDs that directly support
  that specific point.

- Do not attach every source used by the section to every point.

- If source A supports one attraction and source B supports another,
  do not cite both sources for both claims.

- Each ReasonerPoint must independently declare its supporting
  evidence_ids and observation_task_ids.

- For RAG and Web research, use evidence_ids only. Never reference the
  RAG or Web task_id.

- observation_task_ids are reserved for specialized structured tools:
  weather, budget, routing, and map.

CITATION MINIMIZATION:

- For each point, use the smallest sufficient evidence set.

- If one evidence item fully supports the point, prefer that single
  evidence item. Do not add evidence that only partially overlaps.

- Use multiple evidence IDs only when different parts of the point
  require different sources or corroboration is materially useful.

CROSS-SOURCE PRACTICAL ADVICE:

- When a specialized observation such as weather materially affects the
  recommendations, include practical advice connecting them.

- The advice must be a reasonable consequence of the supplied data.

- Do not invent closures, safety restrictions, operating hours, or
  unavailable conditions.

FRESHNESS RULE:

- For time-sensitive claims such as tomorrow's weather, current
  conditions, current closures, current prices, or current availability,
  prefer the corresponding fresh specialized tool or fresh Web evidence.

- Do not use general or historical travel content to strengthen a
  time-specific claim unless it is clearly presented as general context.

- Keep time-specific facts and general destination context in separate
  points when they require different sources.

ITINERARY OUTPUT CONTRACT:

- For ITINERARY, create explicit sections headed Ngày 1, Ngày 2, ...
  for every requested day.
- Group only evidence-backed places and activities under those days.
- Reflect current user preferences from constraints.
- Present this as a reference itinerary, not an optimized route.
- Do not invent exact durations or travel times.

BUDGET GROUNDING CONTRACT:

- The budget calculator performs arithmetic only; it is not a price estimator.
- If no successful calculator observation or price evidence exists, do not
  invent hotel, food, transport, or total costs.
- Separate known costs, explicit assumptions, and unknown costs.

ANSWER DEPTH POLICY:

Research depth determines the expected richness of the answer plan.

BASIC:
- Keep the answer concise and focused.
- Use only the most important points.

ENRICHED:
- Produce a meaningfully detailed answer plan.
- For broad travel recommendation queries, normally create 5 to 7
  distinct recommendation points when evidence supports them.
- Each point should preserve enough grounded detail for the final writer
  to explain what the place or activity is, why it may be relevant, what
  kind of experience it offers, and any useful practical consideration
  supported by context.
- Avoid one-line name lists when evidence provides more useful detail.
- Include cross-cutting practical advice when weather or other
  constraints affect the recommendations.

DEEP:
- Cover the important dimensions comprehensively.
- Organize the answer into multiple useful sections where appropriate.
- Include comparisons, trade-offs, practical considerations, and
  limitations when grounded evidence supports them.

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

    @classmethod
    def _validate_references(
        cls,
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
            if item.tool in cls._SPECIALIZED_TOOLS
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
            for point in section.points:
                referenced_evidence_ids.update(
                    point.evidence_ids
                )

                referenced_task_ids.update(
                    point.observation_task_ids
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

        evidence_ids: list[str] = []

        task_ids: list[str] = []

        for section in output.sections:
            for point in section.points:
                evidence_ids.extend(
                    point.evidence_ids
                )

                task_ids.extend(
                    point.observation_task_ids
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

    @staticmethod
    def _trip_days(plan: ExecutionPlan) -> int | None:
        for constraint in plan.constraints:
            if constraint.key not in {"trip_duration", "trip_duration_days", "days"}:
                continue
            if isinstance(constraint.value, int):
                return constraint.value if 1 <= constraint.value <= 14 else None
            match = re.search(r"\b(\d{1,2})\s*ngày\b", str(constraint.value), re.IGNORECASE)
            if match:
                value = int(match.group(1))
                return value if 1 <= value <= 14 else None
        return None

    @classmethod
    def _enforce_itinerary_structure(
        cls,
        output: ReasonerOutput,
        plan: ExecutionPlan,
    ) -> ReasonerOutput:
        if plan.intent != Intent.ITINERARY:
            return output
        days = cls._trip_days(plan)
        if days is None:
            return output

        headings = " ".join(section.heading.casefold() for section in output.sections)
        if all(re.search(rf"\b(?:ngày|day)\s*{day}\b", headings) for day in range(1, days + 1)):
            return output

        points = [point for section in output.sections for point in section.points]
        chunk_size = max(1, math.ceil(len(points) / days)) if points else 1
        sections: list[ReasonerSection] = []
        for day in range(1, days + 1):
            start = (day - 1) * chunk_size
            end = start + chunk_size
            sections.append(
                ReasonerSection(
                    heading=f"Ngày {day}",
                    purpose=f"Lịch trình tham khảo cho ngày {day}",
                    points=points[start:end],
                )
            )

        limitations = list(output.limitations)
        disclaimer = (
            "Lịch trình chỉ mang tính tham khảo và chưa phải lộ trình tối ưu."
        )
        if disclaimer not in limitations:
            limitations.append(disclaimer)
        return output.model_copy(
            update={"sections": sections, "limitations": limitations}
        )

    @staticmethod
    def _enforce_budget_grounding(
        output: ReasonerOutput,
        plan: ExecutionPlan,
        observations: list[ToolObservation],
        research_evidence: list[EvidenceItem],
    ) -> ReasonerOutput:
        if plan.intent != Intent.BUDGET:
            return output
        calculator_succeeded = any(
            item.tool == ToolName.BUDGET and item.status == TaskStatus.SUCCESS
            for item in observations
        )
        if calculator_succeeded or research_evidence:
            return output

        limitation = (
            "Chưa có chi phí do người dùng cung cấp hoặc bằng chứng giá để "
            "ước tính tổng ngân sách một cách đáng tin cậy."
        )
        return output.model_copy(
            update={
                "sections": [
                    ReasonerSection(
                        heading="Thông tin cần bổ sung",
                        purpose="Không suy đoán giá khi thiếu dữ liệu đầu vào",
                        points=[
                            ReasonerPoint(
                                text=(
                                    "Cần chi phí hoặc giả định rõ ràng cho lưu trú, "
                                    "ăn uống và di chuyển trước khi tính tổng."
                                )
                            )
                        ],
                    )
                ],
                "limitations": list(dict.fromkeys([*output.limitations, limitation])),
                "degraded": True,
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
        observations: list[ToolObservation],
        research_evidence: list[EvidenceItem],
        validation: ValidationResult,
        conversation_context: ConversationContext | None = None,
    ) -> ReasonerOutput:
        query = query.strip()
        if not query:
            raise ValueError("query cannot be empty.")

        prompt = self._build_prompt(
            query=query,
            plan=plan,
            observations=observations,
            research_evidence=research_evidence,
            validation=validation,
            conversation_context=conversation_context,
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
            self.llm_runtime.generate_content(
                model=self.model,

                contents=prompt,

                config=types.GenerateContentConfig(
                    temperature=0.2,

                    max_output_tokens=3072,

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

        # Planner is the authority for intent and goal. The Reasoner
        # controls answer structure and grounded content only.
        output = output.model_copy(
            update={
                "answer_type": plan.intent.value,
                "answer_goal": plan.goal,
            }
        )

        output = self._enforce_itinerary_structure(output, plan)
        output = self._enforce_budget_grounding(
            output,
            plan,
            observations,
            research_evidence,
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
