from __future__ import annotations

import json
import logging
import re
from typing import Any

from google.genai import types

from app.core.config import settings
from pipeline.agents.context import ConversationContext

from pipeline.agents.llm_runtime import (
    GeminiRuntime,
)


logger = logging.getLogger(__name__)

from pipeline.agents.schemas import (
    AgentResponse,
    Citation,
    EvidenceItem,
    EvidenceSource,
    ExecutionPlan,
    ReasonerOutput,
    SynthesizerOutput,
    ToolName,
    ToolObservation,
    ValidationResult,
)
from pipeline.agents.tools.utils import format_tool_data_for_presentation


# ============================================================
# SOURCE / CLAIM CALIBRATION
# ============================================================

_SOURCE_CLAIM_CALIBRATION = """
SOURCE AND CLAIM CALIBRATION

You must calibrate wording to the strength of the supplied evidence.

General rules:

1. Never strengthen a claim beyond what the evidence supports.

2. Do NOT describe information as:
   - "official"
   - "officially confirmed"
   - "chính thức"
   - "được xác nhận chính thức"
   - "niêm yết"
   - "giá niêm yết"
   unless the supporting evidence itself clearly establishes that the
   information comes from the relevant official organization, operator,
   authority, or first-party source.

3. If the supporting evidence comes from third-party websites, use
   neutral wording such as:
   - "Các nguồn hiện tìm được ghi nhận..."
   - "Theo các nguồn web được truy xuất..."
   - "Mức giá được các nguồn tham khảo ghi nhận..."

4. For prices, opening hours, operating status, and temporary events,
   recommend direct verification when the evidence is not clearly from
   an official source.

5. Never invent a source authority level that is not present in the
   evidence.
""".strip()


# ============================================================
# SYNTHESIZER
# ============================================================


class TravelSynthesizer:
    """
    Generate the final Vietnamese answer and resolve citations.

    Gemini may emit only internal source markers. URLs, citation
    numbers, and citation metadata are resolved deterministically.
    """

    _MARKER_PATTERN = re.compile(
        r"\[\[(evidence|tool):([^\[\]\s]+)\]\]"
    )

    _MARKER_COMPONENT_PATTERN = re.compile(
        r"^(evidence|tool)\s*:\s*([^\[\],\s]+)$"
    )

    _ANY_DOUBLE_BRACKET_PATTERN = re.compile(
        r"\[\[[^\[\]\n]*\]\]"
    )

    _NUMERIC_CITATION_PATTERN = re.compile(
        r"\[\d+\]"
    )

    _CITATION_SPACING_PATTERN = re.compile(
        r"\][ \t]+(?=\[\d+\])"
    )

    _URL_PATTERN = re.compile(
        r"https?://",
        re.IGNORECASE,
    )

    _TOOL_SOURCE_TYPES: dict[
        ToolName,
        EvidenceSource,
    ] = {
        ToolName.WEATHER: EvidenceSource.WEATHER,
        ToolName.MAP_LOCATION: EvidenceSource.MAP,
        ToolName.ROUTING: EvidenceSource.ROUTING,
        ToolName.BUDGET: EvidenceSource.CALCULATION,
    }

    _TOOL_TITLES: dict[ToolName, str] = {
        ToolName.WEATHER: "Weather",
        ToolName.MAP_LOCATION: "Map location",
        ToolName.ROUTING: "Routing",
        ToolName.BUDGET: "Budget calculation",
    }

    _SPECIALIZED_TOOLS = frozenset(
        _TOOL_SOURCE_TYPES
    )

    _DETAIL_INSTRUCTIONS = {
        "BASIC": (
            "Aim for a concise answer, roughly 150-300 words "
            "when the available information supports it."
        ),
        "ENRICHED": (
            "Aim for a moderately detailed answer, roughly "
            "450-750 words when sufficient grounded "
            "information is available."
        ),
        "DEEP": (
            "Aim for a detailed answer, roughly 800-1200 "
            "words when sufficient grounded information "
            "is available."
        ),
    }

    def __init__(
        self,
        *,
        max_evidence_chars: int = 2200,
        llm_runtime: GeminiRuntime | None = None,
    ) -> None:
        self.llm_runtime = (
            llm_runtime
            if llm_runtime is not None
            else GeminiRuntime()
        )

        self.model = settings.gemini_model

        self.max_evidence_chars = (
            max_evidence_chars
        )

    # ========================================================
    # REASONER REFERENCES
    # ========================================================

    @staticmethod
    def _ordered_unique(
        values: list[str],
    ) -> list[str]:
        return list(
            dict.fromkeys(values)
        )

    @classmethod
    def _reasoner_reference_ids(
        cls,
        reasoner_output: ReasonerOutput,
    ) -> tuple[list[str], list[str]]:
        evidence_ids: list[str] = []

        task_ids: list[str] = []

        for section in reasoner_output.sections:
            for point in section.points:
                evidence_ids.extend(
                    point.evidence_ids
                )
                task_ids.extend(
                    point.observation_task_ids
                )

        return (
            cls._ordered_unique(evidence_ids),
            cls._ordered_unique(task_ids),
        )

    @staticmethod
    def _index_evidence(
        evidence: list[EvidenceItem],
    ) -> dict[str, EvidenceItem]:
        output: dict[str, EvidenceItem] = {}

        for item in evidence:
            if item.evidence_id in output:
                raise ValueError(
                    "Duplicate evidence_id: "
                    f"{item.evidence_id}"
                )
            output[item.evidence_id] = item

        return output

    @staticmethod
    def _index_observations(
        observations: list[ToolObservation],
    ) -> dict[str, ToolObservation]:
        output: dict[str, ToolObservation] = {}

        for item in observations:
            if item.tool not in TravelSynthesizer._SPECIALIZED_TOOLS:
                continue

            if item.task_id in output:
                raise ValueError(
                    "Duplicate observation task_id: "
                    f"{item.task_id}"
                )
            output[item.task_id] = item

        return output

    @classmethod
    def _select_referenced_sources(
        cls,
        *,
        reasoner_output: ReasonerOutput,
        research_evidence: list[EvidenceItem],
        observations: list[ToolObservation],
    ) -> tuple[list[EvidenceItem], list[ToolObservation]]:
        evidence_ids, task_ids = (
            cls._reasoner_reference_ids(
                reasoner_output
            )
        )

        evidence_by_id = cls._index_evidence(
            research_evidence
        )
        observations_by_id = cls._index_observations(
            observations
        )

        missing_evidence = [
            item_id
            for item_id in evidence_ids
            if item_id not in evidence_by_id
        ]
        missing_tasks = [
            task_id
            for task_id in task_ids
            if task_id not in observations_by_id
        ]

        if missing_evidence:
            raise ValueError(
                "Reasoner references missing evidence_id(s): "
                + ", ".join(missing_evidence)
            )

        if missing_tasks:
            raise ValueError(
                "Reasoner references missing task_id(s): "
                + ", ".join(missing_tasks)
            )

        return (
            [
                evidence_by_id[item_id]
                for item_id in evidence_ids
            ],
            [
                observations_by_id[task_id]
                for task_id in task_ids
            ],
        )

    # ========================================================
    # PROMPT
    # ========================================================

    def _build_prompt(
        self,
        *,
        query: str,
        plan: ExecutionPlan,
        reasoner_output: ReasonerOutput,
        evidence: list[EvidenceItem],
        observations: list[ToolObservation],
        validation: ValidationResult,
        conversation_context: ConversationContext | None = None,
    ) -> str:
        detail_instruction = (
            self._DETAIL_INSTRUCTIONS.get(
                plan.research_depth.value,
                (
                    "Provide an appropriately detailed "
                    "answer."
                ),
            )
        )

        evidence_context: list[
            dict[str, Any]
        ] = []

        for item in evidence:
            payload = item.model_dump(
                mode="json"
            )

            content = str(
                payload.get("content")
                or ""
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

            payload["content"] = content
            evidence_context.append(payload)

        context: dict[str, Any] = {
            "user_query": query,
            "intent": plan.intent.value,
            "research_depth": (
                plan.research_depth.value
            ),
            "reasoner_output": (
                reasoner_output.model_dump(
                    mode="json"
                )
            ),
            "validation": validation.model_dump(
                mode="json"
            ),
            "research_evidence": evidence_context,
            "tool_observations": [
                {
                    **item.model_dump(mode="json"),
                    "data": format_tool_data_for_presentation(item.data),
                }
                for item in observations
            ],
            "response_modifier": (
                plan.response_modifier.value
                if plan.response_modifier is not None
                else None
            ),
            "previous_answer": (
                conversation_context.active_task.previous_answer
                if conversation_context is not None
                and conversation_context.active_task is not None
                else None
            ),
        }

        return f"""
You are the final response writer for a Vietnamese travel assistant.

Write a clear, useful answer in Vietnamese based only on the supplied
structured answer plan and source data.

Use ReasonerOutput as the primary answer structure.

You may enrich each section with additional relevant details from the
supplied research evidence and successful tool observations, provided
every added factual claim is grounded and correctly cited.

The ReasonerOutput provides grounding at the individual point level.

For each factual point:

- Use only the evidence_ids and observation_task_ids listed on that
  ReasonerPoint.

- If you add a new grounded detail directly from the supplied source
  data, cite only the exact source that supports that added detail.

- Do not copy all evidence IDs from neighboring points.

- Prefer the smallest sufficient citation set.

For RAG and Web research, use evidence markers only. Tool markers are
reserved for weather, budget, routing, and map observations.

FRESHNESS POLICY:

- Use fresh specialized observations for time-sensitive claims such as
  tomorrow's weather, current conditions, prices, closures, or
  availability.

- Do not merge general destination background with a time-specific claim
  as though both describe the same time period.

{_SOURCE_CLAIM_CALIBRATION}

For travel recommendations:

- Do not merely enumerate place names.

- Briefly explain what makes notable places interesting when the
  supplied evidence supports it.

- Organize recommendations into useful groups when appropriate, such
  as nature, city-center, culture, check-in, family, or indoor/outdoor.

- Connect weather conditions to practical travel choices when relevant.

- Prioritize useful decision-making information over generic travel
  prose.

- Avoid decorative factual-sounding descriptions that are not explicitly
  supported by the supplied evidence.

- Stylistic wording is allowed only when it does not introduce a new
  factual characterization.

- For a "where should I go" request, keep the answer about places to visit
  and relevant activities. Do not insert accommodation, hotels, MICE, golf,
  or generic tourism-industry material unless requested.
- Omit a reasoner point if its primary substance is accommodation or lodging
  and the user asked broadly for places to visit or activities.

- Treat weather probabilities cautiously. Do not turn a modest chance of
  rain into a guarantee of good or bad conditions; offer a proportionate
  backup suggestion when the grounded plan includes one.

FOLLOW-UP REFINEMENT:

- EXPAND means more useful detail about the same task and the same main
  recommendations. It never means adding unrelated topics.
- CONDENSE means a shorter rendering of the same answer with its key facts
  preserved.
- ADD_OPTIONS should prioritize supported options not already named in the
  previous answer.
- Explicit current-turn constraints always override prior context.

NUMBER PRESENTATION:

- Present weather values for people, not as raw API floats: use sensible
  rounded temperatures, whole percentages, and about one decimal place for
  small rain amounts when appropriate.
- Do not imply precision beyond the supplied presentation data.

ANSWER EXPANSION POLICY:

ReasonerOutput defines the structure and grounding plan. It is not a
sentence-by-sentence final answer.

When evidence supports it, expand each ReasonerPoint into useful natural
language explanation rather than simply paraphrasing its text.

For ENRICHED responses:

- Normally explain each major recommendation in 1 to 3 sentences.

- Explain why a place or activity may be worth considering.

- Add grounded practical context from the evidence when useful.

- Organize related recommendations into readable bullets or short
  paragraphs.

- Include a short practical takeaway when weather or other constraints
  materially affect the trip.

- Avoid filler, repetition, generic travel enthusiasm, and unsupported
  descriptions.

For BASIC responses, be concise.

For DEEP responses, provide substantially more context and
decision-support detail.

ANSWER LENGTH GUIDANCE:

{detail_instruction}

These are soft targets. Never add unsupported material merely to reach a
word count.

Avoid repeating the same factual information in adjacent sentences.
Combine overlapping weather facts into one concise paragraph.

Citation rules:

1. For a claim grounded in research evidence, append the exact marker
   [[evidence:<evidence_id>]].

2. For weather, budget, routing, map, or other specialized tool facts,
   append the exact marker [[tool:<task_id>]].

3. Use only IDs present in the supplied source data.

4. Never create a URL, Markdown link, footnote, or numeric citation such
   as [1] or [2].

5. Do not alter marker spelling, punctuation, or IDs.

6. Place each marker immediately after the claim it supports. Reuse the
   same marker when the same source supports multiple claims.

7. State warnings and limitations honestly. Do not fill missing data
   with assumptions.

8. Do not mention internal pipeline stages, validation objects, IDs, or
   marker syntax in the prose.

9. Keep suggested follow-ups short and do not place citations or URLs
   inside them.

For ITINERARY, preserve every Ngày 1 / Ngày 2 / ... section from
ReasonerOutput. Do not replace the itinerary with a generic introduction or
an unstructured destination list.

INPUT CONTEXT:

{json.dumps(
    context,
    ensure_ascii=False,
    indent=2,
    default=str,
)}
""".strip()

    # ========================================================
    # DRAFT VALIDATION
    # ========================================================

    @classmethod
    def _validate_llm_text(
        cls,
        draft: SynthesizerOutput,
    ) -> None:
        values = [
            draft.answer_markdown,
            *draft.suggested_followups,
        ]

        if not draft.answer_markdown.strip():
            raise ValueError(
                "Synthesizer returned an empty answer."
            )

        for value in values:
            if cls._URL_PATTERN.search(value):
                raise ValueError(
                    "Synthesizer invented a URL."
                )

            if cls._NUMERIC_CITATION_PATTERN.search(
                value
            ):
                raise ValueError(
                    "Synthesizer emitted a numeric citation."
                )

        for followup in draft.suggested_followups:
            if "[[" in followup or "]]" in followup:
                raise ValueError(
                    "Suggested follow-ups cannot contain "
                    "citation markers."
                )

    # ========================================================
    # CITATION BUILDERS
    # ========================================================

    @staticmethod
    def _evidence_citation(
        *,
        citation_id: str,
        evidence: EvidenceItem,
    ) -> Citation:
        provider = evidence.metadata.get(
            "provider"
        )

        if not isinstance(provider, str):
            provider = None

        metadata = dict(evidence.metadata)

        if evidence.entity is not None:
            metadata.setdefault(
                "entity",
                evidence.entity,
            )

        if evidence.score is not None:
            metadata.setdefault(
                "score",
                evidence.score,
            )

        return Citation(
            citation_id=citation_id,
            evidence_id=evidence.evidence_id,
            title=evidence.title,
            url=evidence.url,
            source_type=evidence.source_type,
            provider=provider,
            metadata=metadata,
        )

    @classmethod
    def _tool_citation(
        cls,
        *,
        citation_id: str,
        observation: ToolObservation,
    ) -> Citation:
        provider = observation.data.get(
            "provider"
        )

        if not isinstance(provider, str):
            provider = None

        title = cls._TOOL_TITLES[
            observation.tool
        ]

        if provider:
            title = f"{title} ({provider})"

        url = observation.data.get("url")

        if not isinstance(url, str):
            url = None

        return Citation(
            citation_id=citation_id,
            task_id=observation.task_id,
            title=title,
            url=url,
            source_type=(
                cls._TOOL_SOURCE_TYPES[
                    observation.tool
                ]
            ),
            tool=observation.tool,
            provider=provider,
            metadata={
                "status": observation.status.value,
            },
        )

    # ========================================================
    # DETERMINISTIC CITATION RESOLVER
    # ========================================================

    @classmethod
    def _normalize_citation_markers(
        cls,
        *,
        answer_markdown: str,
        allowed_evidence_ids: set[str],
        allowed_task_ids: set[str],
        evidence_by_id: dict[str, EvidenceItem],
        observations_by_id: dict[str, ToolObservation],
    ) -> tuple[str, list[str], bool]:
        warnings: list[str] = []
        unsafe = False

        def normalize_group(match: re.Match[str]) -> str:
            nonlocal unsafe
            token = match.group(0)
            inner = token[2:-2].strip()
            parts = [part.strip() for part in inner.split(",")]
            normalized: list[str] = []

            for part in parts:
                component = cls._MARKER_COMPONENT_PATTERN.fullmatch(part)
                if component is None:
                    warnings.append("Malformed citation marker was rejected.")
                    unsafe = True
                    continue

                marker_type, source_id = component.groups()
                if marker_type == "evidence":
                    allowed = (
                        source_id in allowed_evidence_ids
                        and source_id in evidence_by_id
                    )
                else:
                    allowed = (
                        source_id in allowed_task_ids
                        and source_id in observations_by_id
                    )

                if not allowed:
                    warnings.append(
                        f"Unselected citation ID was rejected: {source_id}."
                    )
                    logger.warning(
                        "Invalid citation ID rejected",
                        extra={"marker_type": marker_type, "source_id": source_id},
                    )
                    unsafe = True
                    continue

                normalized.append(f"[[{marker_type}:{source_id}]]")

            if len(parts) > 1 and normalized:
                logger.info(
                    "Citation syntax repaired",
                    extra={"marker_count": len(normalized)},
                )

            return "".join(normalized)

        repaired = cls._ANY_DOUBLE_BRACKET_PATTERN.sub(
            normalize_group,
            answer_markdown,
        )

        unresolved_probe = cls._MARKER_PATTERN.sub("", repaired)
        if "[[" in unresolved_probe or "]]" in unresolved_probe:
            warnings.append("Unresolved citation syntax was rejected.")
            unsafe = True
            repaired = re.sub(
                r"\[\[(?:evidence|tool):[^\n.!?]*",
                "",
                repaired,
            ).replace("]]", "")

        return repaired, list(dict.fromkeys(warnings)), unsafe

    @staticmethod
    def _grounded_fallback_answer(reasoner_output: ReasonerOutput) -> str:
        lines: list[str] = []
        for section in reasoner_output.sections:
            if section.heading.strip():
                lines.append(f"## {section.heading.strip()}")
            for point in section.points:
                markers = [
                    *(
                        f"[[evidence:{item_id}]]"
                        for item_id in point.evidence_ids
                    ),
                    *(
                        f"[[tool:{task_id}]]"
                        for task_id in point.observation_task_ids
                    ),
                ]
                lines.append(f"- {point.text.strip()}{''.join(markers)}")

        if not lines:
            limitations = [
                value.strip()
                for value in reasoner_output.limitations
                if value.strip()
            ]
            return "\n".join(limitations) or (
                "Chưa có đủ thông tin đã kiểm chứng để trả lời an toàn."
            )
        return "\n".join(lines)

    @classmethod
    def _resolve_citations_with_warnings(
        cls,
        *,
        answer_markdown: str,
        reasoner_output: ReasonerOutput,
        research_evidence: list[EvidenceItem],
        observations: list[ToolObservation],
    ) -> tuple[str, list[Citation], list[str]]:
        evidence_ids, task_ids = cls._reasoner_reference_ids(reasoner_output)
        allowed_evidence_ids = set(evidence_ids)
        allowed_task_ids = set(task_ids)
        evidence_by_id = cls._index_evidence(research_evidence)
        observations_by_id = cls._index_observations(observations)

        answer_markdown, warnings, unsafe = cls._normalize_citation_markers(
            answer_markdown=answer_markdown,
            allowed_evidence_ids=allowed_evidence_ids,
            allowed_task_ids=allowed_task_ids,
            evidence_by_id=evidence_by_id,
            observations_by_id=observations_by_id,
        )
        if unsafe:
            answer_markdown = cls._grounded_fallback_answer(reasoner_output)
            warnings.append(
                "The generated answer used invalid citation syntax; a grounded fallback was used."
            )

        marker_numbers: dict[tuple[str, str], int] = {}
        citations: list[Citation] = []

        def replace_marker(match: re.Match[str]) -> str:
            marker_type, source_id = match.groups()
            marker_key = (marker_type, source_id)
            citation_number = marker_numbers.get(marker_key)
            if citation_number is None:
                citation_number = len(citations) + 1
                marker_numbers[marker_key] = citation_number
                if marker_type == "evidence":
                    citation = cls._evidence_citation(
                        citation_id=str(citation_number),
                        evidence=evidence_by_id[source_id],
                    )
                else:
                    citation = cls._tool_citation(
                        citation_id=str(citation_number),
                        observation=observations_by_id[source_id],
                    )
                citations.append(citation)
            return f"[{citation_number}]"

        answer = cls._MARKER_PATTERN.sub(replace_marker, answer_markdown)
        answer = cls._CITATION_SPACING_PATTERN.sub("]", answer)

        if (allowed_evidence_ids or allowed_task_ids) and not citations:
            fallback = cls._grounded_fallback_answer(reasoner_output)
            answer = cls._MARKER_PATTERN.sub(replace_marker, fallback)
            warnings.append(
                "Citation coverage was restored from the grounded answer plan."
            )

        return answer.strip(), citations, list(dict.fromkeys(warnings))

    @classmethod
    def _resolve_citations(
        cls,
        *,
        answer_markdown: str,
        reasoner_output: ReasonerOutput,
        research_evidence: list[EvidenceItem],
        observations: list[ToolObservation],
    ) -> tuple[str, list[Citation]]:
        answer, citations, _warnings = cls._resolve_citations_with_warnings(
            answer_markdown=answer_markdown,
            reasoner_output=reasoner_output,
            research_evidence=research_evidence,
            observations=observations,
        )
        return answer, citations

    # ========================================================
    # USED TOOLS
    # ========================================================

    @staticmethod
    def _used_tools(
        citations: list[Citation],
    ) -> list[ToolName]:
        output: list[ToolName] = []

        for citation in citations:
            tool = citation.tool

            if tool is None:
                if citation.source_type == EvidenceSource.RAG:
                    tool = ToolName.RAG
                elif citation.source_type == EvidenceSource.WEB:
                    tool = ToolName.WEB_SEARCH

            if tool is not None and tool not in output:
                output.append(tool)

        return output

    # ========================================================
    # PUBLIC
    # ========================================================

    def synthesize(
        self,
        *,
        query: str,
        plan: ExecutionPlan,
        reasoner_output: ReasonerOutput,
        observations: list[ToolObservation],
        research_evidence: list[EvidenceItem],
        validation: ValidationResult,
        conversation_context: ConversationContext | None = None,
    ) -> AgentResponse:
        query = query.strip()

        if not query:
            raise ValueError(
                "query cannot be empty."
            )

        selected_evidence, selected_observations = (
            self._select_referenced_sources(
                reasoner_output=reasoner_output,
                research_evidence=research_evidence,
                observations=observations,
            )
        )

        prompt = self._build_prompt(
            query=query,
            plan=plan,
            reasoner_output=reasoner_output,
            evidence=selected_evidence,
            observations=selected_observations,
            validation=validation,
            conversation_context=conversation_context,
        )

        response = self.llm_runtime.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
                response_mime_type="application/json",
                response_json_schema=(
                    SynthesizerOutput
                    .model_json_schema()
                ),
            ),
        )

        response_text = response.text

        if not response_text:
            raise RuntimeError(
                "Gemini Synthesizer returned no JSON output."
            )

        draft = (
            SynthesizerOutput
            .model_validate_json(response_text)
        )

        self._validate_llm_text(draft)

        answer_markdown = draft.answer_markdown
        output_warnings: list[str] = []
        if plan.intent.value == "ITINERARY":
            expected_headings = [
                section.heading
                for section in reasoner_output.sections
                if re.search(r"\b(?:ngày|day)\s*\d+\b", section.heading, re.IGNORECASE)
            ]
            if expected_headings and not all(
                heading.casefold() in answer_markdown.casefold()
                for heading in expected_headings
            ):
                answer_markdown = self._grounded_fallback_answer(reasoner_output)
                output_warnings.append(
                    "The itinerary output contract was restored from the grounded answer plan."
                )

        answer, citations, citation_warnings = self._resolve_citations_with_warnings(
            answer_markdown=answer_markdown,
            reasoner_output=reasoner_output,
            research_evidence=selected_evidence,
            observations=selected_observations,
        )

        return AgentResponse(
            answer=answer,
            citations=citations,
            intent=plan.intent,
            used_tools=self._used_tools(citations),
            suggested_followups=(
                draft.suggested_followups
            ),
            warnings=list(dict.fromkeys([*output_warnings, *citation_warnings])),
            degraded=(
                reasoner_output.degraded
                or bool(output_warnings)
                or bool(citation_warnings)
            ),
        )
