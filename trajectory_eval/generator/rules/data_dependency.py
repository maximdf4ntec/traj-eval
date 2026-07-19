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

        for key, value in step.tool_input.items():

            if not is_candidate_value(value):
                continue

            normalized = normalize_value(value)

            origin = cls._find_first_origin(
                normalized,
                step.index,
                steps,
            )

            if origin is None:
                continue

            origin_step, confidence = origin

            rules.append(
                cls(
                    id=f"data_dep_{step.index}_{key}_{origin_step}",
                    step_index=step.index,
                    param_key=key,
                    param_value=normalized,
                    source_step=origin_step,
                    tool_name=step.tool_name or "",
                    confidence=confidence,
                )
            )

        return rules

    @staticmethod
    def _find_first_origin(
        value: str,
        current_step: int,
        steps: list[Step],
    ) -> Optional[tuple[int, ConfidenceLevel]]:
        """
        Find the earliest tool_result that contains the value.
        """

        for step in steps:

            if step.index >= current_step:
                break

            if step.step_type != StepType.tool_result:
                continue

            parsed = step.tool_output_parsed

            if parsed is None:
                continue

            for fact in extract_facts(parsed):

                if fact.value_str == value:
                    return (
                        step.index,
                        fact.confidence,
                    )

        return None
