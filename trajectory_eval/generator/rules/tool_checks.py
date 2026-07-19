"""Rules h and i — per-step tool parameter and index checks.

These rules operate on a single tool_call Step rather than the full trajectory
and are therefore driven by the ``from_step`` factory classmethod.

ToolIndexRule   (Rule i) — the tool name at this trajectory position is constant.
ToolParamCountRule (Rule h) — the tool receives exactly N parameters.
ToolParamTypeRule  (Rule h) — each parameter has the expected Python type.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType

# TODO seems too strict, maybe we can relax it to allow a range of indexes, e.g. step[5:10].tool_name == "python"
# or maybe drop this rule completely


class ToolIndexRule(HardRule):
    """Rule i: the tool at a given trajectory position must always be the same.

    Attributes:
        expected_tool_name: Tool name observed in the reference trajectory.
    """

    expected_tool_name: str

    polarity: RulePolarity = RulePolarity.positive
    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = StepType.tool_call
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "ToolIndexRule":
        """Compute rule_description and pseudocode from typed fields."""
        self.rule_description = (
            f"The tool at trajectory position {self.step_index} must always be "
            f"'{self.expected_tool_name}'."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the tool-name equality assertion pseudocode."""
        return f'step[{self.step_index}].tool_name == "{self.expected_tool_name}"'

    @classmethod
    def from_step(cls, step: Step) -> "ToolIndexRule":
        """Build a ToolIndexRule from a single tool_call step.

        Args:
            step: A Step of type ``tool_call``.

        Returns:
            A single ToolIndexRule instance.
        """
        return cls(
            id=f"tool_index_{step.index}_name",
            step_index=step.index,
            expected_tool_name=step.tool_name or "",
        )


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
    def from_step(cls, step: Step) -> "ToolParamCountRule":
        """Build a ToolParamCountRule from a single tool_call step.

        Args:
            step: A Step of type ``tool_call`` with a non-empty ``tool_input``.

        Returns:
            A single ToolParamCountRule instance.
        """
        return cls(
            id=f"tool_params_{step.index}_count",
            step_index=step.index,
            tool_name=step.tool_name or "",
            expected_count=len(step.tool_input or {}),
        )


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
    def from_step(
        cls, step: Step, param_key: str, param_value: Any
    ) -> "ToolParamTypeRule":
        """Build a ToolParamTypeRule for one parameter of a tool_call step.

        Args:
            step: A Step of type ``tool_call``.
            param_key: The parameter name to check.
            param_value: The observed value (used to infer the expected type).

        Returns:
            A single ToolParamTypeRule instance.
        """
        return cls(
            id=f"tool_params_{step.index}_{param_key}_type",
            step_index=step.index,
            tool_name=step.tool_name or "",
            param_key=param_key,
            expected_type=type(param_value).__name__,
        )
