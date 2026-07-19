"""Rules h — per-step tool parameter checks (promoted to trajectory-level).

These rules now operate at the trajectory level via ``from_trajectory`` classmethods
that scan all tool_call steps and collect observations for downstream deduplication.

ToolParamCountRule (Rule h) — the tool receives exactly N parameters.
ToolParamTypeRule  (Rule h) — each parameter has the expected Python type.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType, Trajectory


class ToolParamCountRule(HardRule):
    """Rule h (count): the tool must receive exactly the observed number of parameters.

    Attributes:
        tool_name: Name of the tool at this step.
        expected_count: Number of parameters observed in the reference trajectory.
    """

    tool_name: str
    expected_count: int

    polarity: RulePolarity = RulePolarity.positive
    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = StepType.tool_call
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "ToolParamCountRule":
        """Compute rule_description and pseudocode from typed fields."""
        self.rule_description = (
            f"Tool '{self.tool_name}' at step {self.step_index} must receive "
            f"exactly {self.expected_count} parameter(s)."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the parameter-count assertion pseudocode."""
        return f"len(step[{self.step_index}].tool_input) == {self.expected_count}"

    @classmethod
    def from_trajectory(cls, trajectory: Trajectory) -> list["ToolParamCountRule"]:
        """Scan ALL tool_call steps, collect param count per tool.

        Args:
            trajectory: The full trajectory to scan.

        Returns:
            A list of ToolParamCountRule instances — one per tool_call step
            that has tool_input. Deduplication happens downstream.
        """
        rules: list[ToolParamCountRule] = []
        for step in trajectory.steps:
            if step.step_type != StepType.tool_call or not step.tool_input:
                continue
            tool_name = step.tool_name or ""
            rule = cls(
                id=f"tool_params_{step.index}_count",
                step_index=step.index,
                tool_name=tool_name,
                expected_count=len(step.tool_input),
            )
            rules.append(rule)
        return rules


class ToolParamTypeRule(HardRule):
    """Rule h (type): a specific parameter must have the expected Python type.

    Attributes:
        tool_name: Name of the tool at this step.
        param_key: Name of the parameter being checked.
        expected_type: Python type name (e.g. ``"str"``, ``"int"``).
    """

    tool_name: str
    param_key: str
    expected_type: str

    polarity: RulePolarity = RulePolarity.positive
    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = StepType.tool_call
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "ToolParamTypeRule":
        """Compute rule_description and pseudocode from typed fields."""
        self.rule_description = (
            f"Parameter '{self.param_key}' of '{self.tool_name}' at step "
            f"{self.step_index} must be of type {self.expected_type}."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the parameter-type assertion pseudocode."""
        return (
            f"isinstance(step[{self.step_index}].tool_input"
            f'["{self.param_key}"], {self.expected_type})'
        )

    @classmethod
    def from_trajectory(cls, trajectory: Trajectory) -> list["ToolParamTypeRule"]:
        """Scan ALL tool_call steps, collect type observations per (tool, param).

        Args:
            trajectory: The full trajectory to scan.

        Returns:
            A list of ToolParamTypeRule instances — one per (tool, param, step)
            observation. Deduplication happens downstream.
        """
        observations: dict[tuple[str, str], list[ToolParamTypeRule]] = defaultdict(list)

        for step in trajectory.steps:
            if step.step_type != StepType.tool_call or not step.tool_input:
                continue
            tool_name = step.tool_name or ""
            for key, val in step.tool_input.items():
                rule = cls(
                    id=f"tool_params_{step.index}_{key}_type",
                    step_index=step.index,
                    tool_name=tool_name,
                    param_key=key,
                    expected_type=type(val).__name__,
                )
                observations[(tool_name, key)].append(rule)

        # Return ALL observations — deduplication happens downstream
        return [rule for group in observations.values() for rule in group]
