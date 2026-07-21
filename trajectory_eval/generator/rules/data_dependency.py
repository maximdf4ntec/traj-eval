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

from typing import Any, NamedTuple, Optional

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
from trajectory_eval.models.tool import (
    ParameterType,
    SubParameter,
    ToolParameter,
)
from trajectory_eval.models.trajectory import (
    Step,
    StepType,
    Trajectory,
)

ELIGIBLE_TYPES: frozenset[ParameterType] = frozenset(
    {
        ParameterType.file_path,
        ParameterType.command_line,
        ParameterType.code,
        ParameterType.json,
        ParameterType.xml,
        ParameterType.url,
        ParameterType.yaml,
        ParameterType.date,
    }
)


class TypeMatch(NamedTuple):
    """Deduplication key for type-based rules."""

    tool_name: str
    param_key: str
    source_tool_name: str
    detected_type: ParameterType


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

    @staticmethod
    def _extract_types_from_param(
        param: ToolParameter | SubParameter,
    ) -> set[ParameterType]:
        """Recursively extract all eligible detected_types from a parameter tree.

        Traverses the parameter and all nested sub_parameters at arbitrary depth.
        Returns only types that are in ELIGIBLE_TYPES.

        Args:
            param: A ToolParameter or SubParameter to traverse.

        Returns:
            Set of eligible ParameterType values found in the tree.
        """
        result: set[ParameterType] = set()

        if param.detected_type in ELIGIBLE_TYPES:
            result.add(param.detected_type)

        for sub in param.sub_parameters:
            result.update(DataDependencyRule._extract_types_from_param(sub))

        return result

    @classmethod
    def _collect_type_sources(
        cls,
        steps: list[Step],
        up_to_index: int,
    ) -> dict[ParameterType, list[tuple[str, int]]]:
        """Collect type-sources from all tool_result steps before the given index.

        Scans tool_result steps in trajectory order. For each step with non-null
        output_typed, recursively extracts eligible types and records the
        (tool_name, step_index) pair for each.

        Args:
            steps: All trajectory steps.
            up_to_index: Only consider steps with index < up_to_index.

        Returns:
            Mapping from ParameterType to list of (tool_name, step_index) pairs.
        """
        sources: dict[ParameterType, list[tuple[str, int]]] = {}

        for step in steps:
            if step.index >= up_to_index:
                break

            if step.step_type != StepType.tool_result:
                continue

            if step.tool is None or step.tool.output_typed is None:
                continue

            types = cls._extract_types_from_param(step.tool.output_typed)

            for t in types:
                if t not in sources:
                    sources[t] = []
                sources[t].append((step.tool.name, step.index))

        return sources

    @classmethod
    def _type_based_rules(
        cls,
        trajectory: Trajectory,
    ) -> list["DataDependencyRule"]:
        """Generate type-based DataDependencyRules from a trajectory.

        Algorithm:
        1. Iterate tool_call steps in trajectory order.
        2. For each tool_call, collect type-sources from all preceding tool_result steps.
        3. For each input ToolParameter on the tool_call, recursively extract eligible types.
        4. For each eligible type found in input, check if a matching type-source exists.
        5. Apply filters: self-referential exclusion, deduplication.
        6. Emit DataDependencyRule with confidence=potential.

        Args:
            trajectory: The complete trajectory to analyze.

        Returns:
            List of type-based DataDependencyRule instances.
        """
        rules: list[DataDependencyRule] = []
        seen: set[TypeMatch] = set()

        for step in trajectory.steps:
            if step.step_type != StepType.tool_call or step.tool is None:
                continue

            tool_name = step.tool.name

            # Collect all type-sources from preceding tool_result steps
            type_sources = cls._collect_type_sources(trajectory.steps, step.index)

            # Extract eligible types from each input parameter
            for input_param in step.tool.inputs:
                input_types = cls._extract_types_from_param(input_param)

                for detected_type in input_types:
                    if detected_type not in type_sources:
                        continue

                    # Match against each source
                    for source_tool_name, source_step_index in type_sources[
                        detected_type
                    ]:
                        # Self-referential exclusion
                        if source_tool_name == tool_name:
                            continue

                        # Deduplication
                        match_key = TypeMatch(
                            tool_name=tool_name,
                            param_key=input_param.key,
                            source_tool_name=source_tool_name,
                            detected_type=detected_type,
                        )
                        if match_key in seen:
                            continue
                        seen.add(match_key)

                        rules.append(
                            DataDependencyRule(
                                id=f"type_dep_{step.index}_{input_param.key}_{source_step_index}",
                                step_index=step.index,
                                param_key=input_param.key,
                                param_value=f"type:{detected_type.value}",
                                source_step=source_step_index,
                                source_tool_name=source_tool_name,
                                tool_name=tool_name,
                                confidence=ConfidenceLevel.potential,
                            )
                        )

        return rules

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

        # Append type-based rules after value-based rules
        rules.extend(cls._type_based_rules(trajectory))

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
