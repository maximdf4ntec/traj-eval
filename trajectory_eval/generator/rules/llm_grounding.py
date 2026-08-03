"""Rule m — LLM Response Grounding / Data Lineage.

Traces entity references in ``llm_response`` steps back to their origin in
prior ``tool_result`` outputs. This is the LLM-facing counterpart of
:class:`DataDependencyRule` (tool→tool lineage): it establishes whether
data produced by tools actually flows into the LLM's reasoning.

Two kinds of rules are emitted:

* **Positive (grounded)**: An entity in the LLM response can be traced to a
  specific prior ``tool_result``. This confirms tool→LLM data lineage —
  the LLM is referencing verified environment state. Confidence is
  ``high`` or ``medium`` depending on entity type specificity.

* **Negative (ungrounded)**: An entity appears in the LLM response but
  cannot be found in any of the N preceding ``tool_result`` outputs.
  This is a *potential* hallucination signal — the LLM may be
  fabricating references. Confidence is ``potential`` because the
  entity might legitimately come from the user prompt, system
  instructions, or the LLM's training data rather than being a
  hallucination.

Entity types detected
----------------------
* ``file_path``      — Unix / Windows paths containing a separator and extension.
* ``hash_id``        — ``#<digits>`` references (issues, PRs, tickets).
* ``commit_sha``     — 7-40 character lowercase hex strings (git's minimum
                       abbreviation length is 7; pure-decimal runs are
                       discarded to avoid matching timestamps).
* ``backtick_ident`` — backtick-quoted identifiers (4-80 chars) containing
                       at least one dot, slash, or underscore.

By default only ``file_path``, ``hash_id``, and ``commit_sha`` are checked
(see ``_DEFAULT_ENTITY_TYPES``). ``backtick_ident`` is opt-in: agents very
often reference an identifier by name in passing without asserting anything
about verified state, so treating every backtick-quoted token as a
groundable claim produces a high false-positive rate. Pass
``entity_types=_ALL_ENTITY_TYPES`` to ``from_trajectory`` to include it.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.generator.utils.fact_normalizer import extract_file_paths

_DEFAULT_CONTEXT_WINDOW: int = 10

# Entity types considered safe defaults: near-always genuine claims about
# observed environment state, rather than incidental naming.
_DEFAULT_ENTITY_TYPES: frozenset[str] = frozenset(
    {"file_path", "hash_id", "commit_sha"}
)
_ALL_ENTITY_TYPES: frozenset[str] = _DEFAULT_ENTITY_TYPES | {"backtick_ident"}

# ── Entity extraction patterns ──────────────────────────────────────────────

# Issue / PR / ticket ID: #123. The negative lookbehind excludes the common
# no-space CSS pattern `color:#123456`, while still matching ordinary prose
# references like "see #123" or "fixes #4567". This is a partial guard, not
# a complete one — a bare "#000" in prose unrelated to CSS is still
# ambiguous and will still match; there's no reliable way to disambiguate
# from text content alone.
_RE_HASH_ID = re.compile(r"(?<!:)#\d+\b")

# 7-40 char lowercase hex string. Matches are post-filtered in
# _extract_entities to drop pure-decimal runs, since [0-9a-f] also accepts
# plain digit sequences (e.g. a 10-13 digit unix timestamp).
_RE_COMMIT_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")

# Backtick-quoted identifiers (4-80 chars) that contain a structural char.
_RE_BACKTICK_IDENT = re.compile(r"`([a-zA-Z0-9_./:@-]{4,80})`")


def _extract_entities(text: str) -> list[tuple[str, str]]:
    """Extract named entity references from *text*.

    Deduplicates results while preserving first-occurrence order.

    Args:
        text: LLM response text to scan.

    Returns:
        List of ``(entity_type, entity_value)`` tuples.
    """
    seen: set[str] = set()
    entities: list[tuple[str, str]] = []

    def _add(kind: str, value: str) -> None:
        if value not in seen:
            seen.add(value)
            entities.append((kind, value))

    # Use the shared canonical file path extraction from fact_normalizer.
    for path in extract_file_paths(text):
        _add("file_path", path)
    for m in _RE_HASH_ID.finditer(text):
        _add("hash_id", m.group(0))
    for m in _RE_COMMIT_SHA.finditer(text):
        val = m.group(0)
        if val.isdigit():
            continue  # pure-decimal run (e.g. a timestamp) — not a SHA
        _add("commit_sha", val)
    for m in _RE_BACKTICK_IDENT.finditer(text):
        val = m.group(1)
        if any(c in val for c in (".", "/", "_")):
            _add("backtick_ident", val)

    return entities


def _stringify_tool_output(value: object) -> str:
    """Coerce a tool_result output of unknown shape into a searchable string.

    ``tool_output`` may hold a plain string, or a structured object (dict /
    list) when a tool returns parsed JSON rather than raw text. Structured
    values are serialized so entity substring matching still works against
    their contents, instead of raising when ``"\\n".join`` receives a
    non-string item.

    Args:
        value: The raw ``tool_output`` value of a tool_result step.

    Returns:
        A string representation suitable for substring search. Empty string
        for ``None``.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def _build_context(steps: list[Step], before_index: int, window: int) -> str:
    """Concatenate up to *window* tool_result outputs before *before_index*.

    Walks the step list in reverse order to collect the N most-recent
    ``tool_result`` outputs before the given index.

    Args:
        steps: Full step list (assumed sorted by ``.index``).
        before_index: Index of the step whose context is being built (exclusive).
        window: Maximum number of prior tool_result steps to include.

    Returns:
        Concatenated output strings joined by newlines; empty when no prior
        results exist.
    """
    results: list[str] = []
    for step in reversed(steps):
        if step.index >= before_index:
            continue
        if step.step_type != StepType.tool_result:
            continue
        results.append(_stringify_tool_output(step.tool_output))
        if len(results) >= window:
            break
    return "\n".join(results)


def _find_grounding_source(
    entity_type: str,
    entity_value: str,
    steps: list[Step],
    before_index: int,
    window: int,
) -> Optional[int]:
    """Find the earliest tool_result step that contains *entity_value*.

    Searches the N most-recent ``tool_result`` steps before *before_index*
    for a (normalized) substring match. Returns the step index of the first
    match, or ``None`` if the entity is ungrounded.

    Args:
        entity_type: Category of the entity (affects normalization).
        entity_value: The raw entity string to search for.
        steps: Full step list (assumed sorted by ``.index``).
        before_index: Exclusive upper bound on step index.
        window: Maximum number of prior tool_result steps to search.

    Returns:
        Step index of the grounding source, or ``None``.
    """
    normalized_value = _normalize_for_match(entity_type, entity_value)
    candidates: list[Step] = []

    for step in reversed(steps):
        if step.index >= before_index:
            continue
        if step.step_type != StepType.tool_result:
            continue
        candidates.append(step)
        if len(candidates) >= window:
            break

    # Search in chronological order (earliest first) to find the origin.
    for step in reversed(candidates):
        output_text = _stringify_tool_output(step.tool_output)
        if entity_type == "file_path":
            output_text = output_text.replace("\\", "/")
        if normalized_value in output_text:
            return step.index

    return None


def _normalize_for_match(entity_type: str, value: str) -> str:
    """Normalize cosmetic variation before a verbatim containment check.

    Only ``file_path`` values are normalized (unify path separators and
    strip a leading ``./``), since path formatting is the main source of
    false-positive "ungrounded" flags on an otherwise-correct reference
    (e.g. ``./boltons/tableutils.py`` vs ``boltons/tableutils.py``). Other
    entity types are compared as-is: case matters for identifiers and commit
    SHAs, and lowering it could mask a genuine violation rather than a
    cosmetic difference.

    Args:
        entity_type: One of the extracted entity type strings.
        value: The raw entity value.

    Returns:
        A normalized value for ``entity_type == "file_path"``; ``value``
        unchanged otherwise.
    """
    if entity_type != "file_path":
        return value
    normalized = value.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _safe_id_fragment(value: str) -> str:
    """Return a short, collision-resistant fragment of *value* for rule IDs.

    Combines a human-readable slug with a short hash suffix so two distinct
    entities sharing a long common prefix (e.g. two dated file variants)
    don't collapse to the same rule ID after truncation.
    """
    slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", value)[:20].rstrip("_")
    digest = hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{slug}_{digest}" if slug else digest


class LlmGroundingRule(HardRule):
    """Rule m: data lineage between tool_results and LLM responses.

    Establishes whether entity references in LLM responses can be traced
    to specific prior ``tool_result`` outputs (tool→LLM data flow), similar
    to how :class:`DataDependencyRule` establishes tool→tool lineage.

    **Positive rules** (grounded): An entity is confirmed to originate from
    a specific tool_result step. This is a high-confidence data lineage
    assertion — the LLM is demonstrably using verified environment data.

    **Negative rules** (ungrounded): An entity cannot be found in any
    recent tool_result. This is a *potential* hallucination signal with
    lower confidence, since the entity might legitimately come from the
    user prompt, system message, or model knowledge.

    Attributes:
        entity_type: Category of the entity (``"file_path"``,
            ``"hash_id"``, ``"commit_sha"``, ``"backtick_ident"``).
        entity_value: The verbatim entity string extracted from the response.
        context_window: Number of prior tool_result steps searched.
        source_step: Step index of the tool_result that grounds this entity,
            or ``None`` if ungrounded.
    """

    entity_type: str
    entity_value: str
    context_window: int
    source_step: Optional[int] = None

    # Defaults — overridden per-instance in from_trajectory based on
    # whether the entity is grounded or not.
    polarity: RulePolarity = RulePolarity.positive
    scope: RuleScope = RuleScope.frame
    step_type: StepType = StepType.llm_response
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "LlmGroundingRule":
        """Compute rule_description and pseudocode from typed fields."""
        if self.source_step is not None:
            self.rule_description = (
                f"LLM response at step {self.step_index} references "
                f"{self.entity_type} {self.entity_value!r} which originates from "
                f"tool_result at step {self.source_step}."
            )
        else:
            self.rule_description = (
                f"LLM response at step {self.step_index} references "
                f"{self.entity_type} {self.entity_value!r} which was not found in any "
                f"of the {self.context_window} preceding tool_result output(s)."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the grounding-check assertion pseudocode."""
        if self.source_step is not None:
            return (
                f"{self.entity_value!r} in "
                f"step[{self.source_step}].tool_output  # grounded"
            )
        return (
            f"{self.entity_value!r} in "
            f"_build_context(trajectory.steps, before_index={self.step_index}, "
            f"window={self.context_window})"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        context_window: int = _DEFAULT_CONTEXT_WINDOW,
        entity_types: frozenset[str] = _DEFAULT_ENTITY_TYPES,
    ) -> list["LlmGroundingRule"]:
        """Build grounding rules for entity references in LLM responses.

        For each ``llm_response`` step, every extracted entity of an
        enabled type is checked (after normalization) against the
        concatenated text of up to *context_window* preceding
        ``tool_result`` outputs.

        Two classes of rules are emitted:

        * **Grounded (positive)**: The entity is found in a specific prior
          ``tool_result``. This confirms tool→LLM data lineage. Emitted
          with ``polarity=positive`` and ``confidence=high`` (file_path,
          commit_sha) or ``confidence=medium`` (hash_id).

        * **Ungrounded (negative)**: The entity cannot be found in any
          preceding ``tool_result``. This is a potential hallucination
          signal. Emitted with ``polarity=negative`` and
          ``confidence=potential``.

        Args:
            trajectory: The full trajectory to analyse.
            context_window: Number of prior tool_result steps to search.
                Defaults to :data:`_DEFAULT_CONTEXT_WINDOW`.
            entity_types: Which entity categories to check. Defaults to
                :data:`_DEFAULT_ENTITY_TYPES` (``file_path``, ``hash_id``,
                ``commit_sha``). Pass :data:`_ALL_ENTITY_TYPES` to also
                include ``backtick_ident``, which is noisier and opt-in.

        Returns:
            List of LlmGroundingRule instances (both grounded and ungrounded).
        """
        steps = trajectory.steps
        rules: list[LlmGroundingRule] = []

        for step in steps:
            if step.step_type != StepType.llm_response:
                continue
            response = step.response or ""
            if not response.strip():
                continue

            entities = _extract_entities(response)

            for entity_type, entity_value in entities:
                if entity_type not in entity_types:
                    continue

                source_step = _find_grounding_source(
                    entity_type, entity_value, steps, step.index, context_window
                )

                if source_step is not None:
                    # Grounded: confirmed tool→LLM data lineage.
                    confidence = _grounded_confidence(entity_type)
                    rules.append(
                        cls(
                            id=(
                                f"llm_grounding_{step.index}"
                                f"_{entity_type}"
                                f"_{_safe_id_fragment(entity_value)}"
                            ),
                            step_index=step.index,
                            entity_type=entity_type,
                            entity_value=entity_value,
                            context_window=context_window,
                            source_step=source_step,
                            polarity=RulePolarity.positive,
                            confidence=confidence,
                        )
                    )
                else:
                    # Ungrounded: potential hallucination (low confidence).
                    rules.append(
                        cls(
                            id=(
                                f"llm_grounding_{step.index}"
                                f"_{entity_type}"
                                f"_{_safe_id_fragment(entity_value)}"
                            ),
                            step_index=step.index,
                            entity_type=entity_type,
                            entity_value=entity_value,
                            context_window=context_window,
                            source_step=None,
                            polarity=RulePolarity.negative,
                            confidence=ConfidenceLevel.potential,
                        )
                    )

        return rules


def _grounded_confidence(entity_type: str) -> ConfidenceLevel:
    """Return the confidence level for a grounded entity by type.

    File paths and commit SHAs are highly specific identifiers — if they
    appear in both a tool_result and an LLM response, the lineage is
    near-certain. Hash IDs (``#123``) are shorter and more ambiguous.

    Args:
        entity_type: The entity category string.

    Returns:
        Confidence level for the grounded lineage assertion.
    """
    if entity_type in ("file_path", "commit_sha"):
        return ConfidenceLevel.high
    return ConfidenceLevel.medium
