"""Rule a — Tool Invocation Redundancy Ratio.

Two tool calls are duplicates when they share the same tool name and
JSON-serialised tool_input.  The redundancy rate is the fraction of calls
that are duplicates.  The rule fires when that fraction exceeds *max_rate*.
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


class RedundancyRateRule(HardRule):
    """Rule a: the trajectory's tool-call redundancy rate must not exceed a threshold.

    Attributes:
        max_rate: Maximum allowed fraction of duplicate tool calls.
        observed_rate: Fraction of duplicate calls observed in the trajectory.
        duplicate_count: Number of duplicate calls found.
        total_count: Total number of tool calls in the trajectory.
    """

    # Rule-specific typed fields.
    max_rate: float
    observed_rate: float
    duplicate_count: int
    total_count: int

    # Class-level defaults for base Rule fields.
    polarity: RulePolarity = RulePolarity.neutral
    scope: RuleScope = RuleScope.global_
    step_type: Optional[StepType] = None
    confidence: ConfidenceLevel = ConfidenceLevel.high

    # Derived text fields — computed by the validator below.
    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "RedundancyRateRule":
        """Compute rule_description and pseudocode from typed fields."""
        self.rule_description = (
            f"Tool invocation redundancy rate must not exceed "
            f"{self.max_rate:.0%}. Observed: {self.observed_rate:.1%} "
            f"({self.duplicate_count} duplicate(s) out of "
            f"{self.total_count} total calls)."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the redundancy-rate assertion pseudocode.

        Returns:
            Assertion string comparing the observed rate to the threshold.
        """
        return (
            f"duplicate_tool_calls(trajectory) / total_tool_calls(trajectory)"
            f" <= {self.max_rate}  # observed: {self.observed_rate:.3f}"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        max_rate: float = 0.25,
    ) -> list["RedundancyRateRule"]:
        """Build a redundancy-rate rule instance from the full trajectory.

        Args:
            trajectory: The full trajectory to analyse.
            max_rate: Maximum allowed redundancy fraction.

        Returns:
            A single-element list, or an empty list when there are no tool calls.
        """
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]
        total = len(tool_calls)
        if total == 0:
            return []

        seen: set[tuple[str, str]] = set()
        duplicates = 0
        for step in tool_calls:
            key = tool_call_signature(step)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)

        return [
            cls(
                id="global_redundancy_1",
                step_index=None,
                max_rate=max_rate,
                observed_rate=duplicates / total,
                duplicate_count=duplicates,
                total_count=total,
            )
        ]
