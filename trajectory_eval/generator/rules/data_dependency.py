"""
Rule d — Step-to-Step Data Dependency (Lineage Validation).

A lineage rule is generated when a tool_call parameter can be traced back to
an atomic value produced by an earlier tool_result.

Unlike the initial implementation, this version:

- Searches ALL previous tool_result steps.
- Uses normalized atomic values instead of substring matching.
- Tracks the FIRST occurrence (birthplace) of a value.
- Computes confidence from the matched evidence.
"""

from __future__ import annotations

from typing import Optional

from pydantic import model_validator

from trajectory_eval.generator.utils.fact_normalizer import (
    calculate_confidence,
    extract_facts,
    normalize_value,
    is_candidate_value,
)

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import (
    Step,
    StepType,
    Trajectory,
)


class DataDependencyRule(HardRule):
    """
    Rule d:
    Tool-call parameters must originate from an earlier tool_result.
    """

    param_key: str
    param_value: str
    source_step: int
    source_tool_name: str = ""
    tool_name: str

    polarity: RulePolarity = RulePolarity.neutral
    scope: RuleScope = RuleScope.frame
    step_type: Optional[StepType] = StepType.tool_call
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _populate_fields(self) -> "DataDependencyRule":
        self.rule_description = (
            f"Parameter '{self.param_key}' of tool "
            f"'{self.tool_name}' at step {self.step_index} "
            f"must originate from tool_result step "
            f"{self.source_step} or later propagated values."
        )

        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        return (
            f"assert value_origin(step[{self.step_index}]."
            f'tool_input["{self.param_key}"]) == '
            f"step[{self.source_step}]"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
    ) -> list["DataDependencyRule"]:

        rules: list[DataDependencyRule] = []

        for step in trajectory.steps:

            if step.step_type != StepType.tool_call or not step.tool_input:
                continue

            rules.extend(cls._rules_for_step(step, trajectory.steps))

        return rules

    @classmethod
    def _rules_for_step(
        cls,
        step: Step,
        steps: list[Step],
    ) -> list["DataDependencyRule"]:

        rules: list[DataDependencyRule] = []
        # Track which (tool, param_key, source_tool) combos we've already emitted
        # to avoid duplicates from multiple values in one param.
        seen_lineage: set[tuple[str, str, str]] = set()

        for key, value in step.tool_input.items():

            if not is_candidate_value(value):
                continue

            # Extract individual trackable values from the parameter.
            candidates = cls._extract_trackable_values(value)

            for candidate in candidates:
                origin = cls._find_first_origin(
                    candidate,
                    step.index,
                    steps,
                )

                if origin is None:
                    continue

                origin_step, confidence = origin

                # Resolve source tool name from the tool_call preceding
                # the source tool_result.
                source_tool = ""
                for s in reversed(steps):
                    if s.index < origin_step and s.step_type == StepType.tool_call:
                        source_tool = s.tool_name or ""
                        break

                # Skip self-referential lineage (same tool consuming its own
                # output) — not useful as a provenance invariant.
                if source_tool == (step.tool_name or ""):
                    continue

                # Only emit one rule per (step, param, source_tool) to avoid
                # inflating support from multiple values in a single param.
                lineage_key = (step.tool_name or "", key, source_tool)
                if lineage_key in seen_lineage:
                    continue
                seen_lineage.add(lineage_key)

                rules.append(
                    cls(
                        id=f"data_dep_{step.index}_{key}_{origin_step}",
                        step_index=step.index,
                        param_key=key,
                        param_value=candidate,
                        source_step=origin_step,
                        source_tool_name=source_tool,
                        tool_name=step.tool_name or "",
                        confidence=confidence,
                    )
                )

        return rules

    @staticmethod
    def _extract_trackable_values(value: Any) -> list[str]:
        """Extract individual trackable values from a parameter.

        For plain short values, returns the normalized value.
        For strings that contain file paths, extracts those paths.
        """
        import re

        normalized = normalize_value(value)
        if not normalized:
            return []

        results: list[str] = []

        # Extract file paths (absolute Unix paths).
        path_pattern = re.compile(r"/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10}")
        paths = path_pattern.findall(normalized)
        if paths:
            results.extend(paths)

        # If no paths found and value is short enough, use as-is.
        if not results and len(normalized) <= 200:
            results.append(normalized)

        return results

    @staticmethod
    def _find_first_origin(
        value: str,
        current_step: int,
        steps: list[Step],
    ) -> Optional[tuple[int, ConfidenceLevel]]:
        """
        Find the earliest tool_result that contains the value.

        Searches both structured (JSON-parsed) output and raw text output.
        """

        for step in steps:

            if step.index >= current_step:
                break

            if step.step_type != StepType.tool_result:
                continue

            # Try structured output first.
            parsed = step.tool_output_parsed

            if parsed is not None:
                for fact in extract_facts(parsed):
                    if fact.value_str == value:
                        return (
                            step.index,
                            fact.confidence,
                        )

            # Fallback: raw text substring search.
            raw_output = step.tool_output or ""
            if value in raw_output:
                return (
                    step.index,
                    calculate_confidence(value),
                )

        return None
