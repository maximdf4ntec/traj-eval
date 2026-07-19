"""Rule e — Multi-Turn Cycle Breaker.

Two tool calls are identical when they share the same tool_name and
JSON-serialised tool_input.  A match within the last *horizon* tool_call
steps indicates a potential agent loop.
"""

from __future__ import annotations

from typing import Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import StepType, Trajectory
from trajectory_eval.generator.rules._helpers import tool_call_signature


class CycleBreakRule(HardRule):
    """Rule e: a tool call must not repeat an identical call within the horizon window.

    Attributes:
        prior_step: Step index of the earlier identical call.
        repeated_tool_name: Name of the tool that was repeated.
        horizon: The cognitive-horizon window in which the repeat was detected.
    """

    # Rule-specific typed fields.
    prior_step: int
    repeated_tool_name: str
    horizon: int

    # Class-level defaults.
    polarity: RulePolarity = RulePolarity.neutral
    scope: RuleScope = RuleScope.frame
    step_type: Optional[StepType] = StepType.tool_call
    confidence: ConfidenceLevel = ConfidenceLevel.high

    # Derived text fields.
    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "CycleBreakRule":
        """Compute rule_description and pseudocode from typed fields."""
        self.rule_description = (
            f"Step {self.step_index} repeats the identical "
            f"'{self.repeated_tool_name}' call from step {self.prior_step} "
            f"within a {self.horizon}-step cognitive horizon -- "
            f"potential agent cycle."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the cycle-detection assertion pseudocode.

        Returns:
            Assertion string noting the repeated call within the horizon.
        """
        return (
            f"step[{self.step_index}] != step[{self.prior_step}]"
            f"  # identical call within {self.horizon}-step window"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        horizon: int = 5,
    ) -> list["CycleBreakRule"]:
        """Detect repeated identical tool calls within a cognitive horizon.

        Args:
            trajectory: The full trajectory to analyse.
            horizon: Maximum number of preceding tool_call steps to inspect.

        Returns:
            One rule per (current-step, matching-prior-step) pair found.
        """
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]
        rules: list[CycleBreakRule] = []

        for i, step in enumerate(tool_calls):
            key = tool_call_signature(step)
            for prior in tool_calls[max(0, i - horizon) : i]:
                if tool_call_signature(prior) == key:
                    rules.append(
                        cls(
                            id=f"cycle_{step.index}_vs_{prior.index}",
                            step_index=step.index,
                            prior_step=prior.index,
                            repeated_tool_name=step.tool_name or "",
                            horizon=horizon,
                        )
                    )

        return rules
