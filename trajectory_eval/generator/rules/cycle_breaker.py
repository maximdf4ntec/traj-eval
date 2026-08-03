"""Rule e — Multi-Turn Cycle Breaker.

Two tool calls are identical when they share the same tool_name and
JSON-serialised tool_input.  Consecutive identical calls indicate a
potential agent loop.  Observations are consolidated per unique call
signature: one rule per distinct repeated invocation, reporting the
earliest occurrence, total repetition count, and the step span.
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
from trajectory_eval.models.trajectory import StepType, Trajectory
from trajectory_eval.generator.rules._helpers import tool_call_signature


class CycleBreakRule(HardRule):
    """Rule e: a tool call must not repeat an identical call within the trajectory.

    Observations are consolidated per unique call signature — one rule per
    distinct (tool_name, params) combination that appeared more than once.

    Attributes:
        prior_step: Step index of the earliest identical call.
        repeated_tool_name: Name of the tool that was repeated.
        horizon: Step span from the earliest to the latest occurrence.
        repetition_count: Total number of times this exact call appeared.
    """

    # Rule-specific typed fields.
    prior_step: int
    repeated_tool_name: str
    horizon: int
    repetition_count: int = 2

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
            f"Tool '{self.repeated_tool_name}' called {self.repetition_count} "
            f"times with identical parameters (first at step {self.prior_step}, "
            f"last at step {self.step_index}, span {self.horizon} steps) -- "
            f"potential agent cycle."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the cycle-detection assertion pseudocode.

        Returns:
            Assertion string noting the repeated calls.
        """
        return (
            f"count(identical_calls('{self.repeated_tool_name}')) == 1"
            f"  # found {self.repetition_count} occurrences spanning "
            f"steps {self.prior_step}..{self.step_index}"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        horizon: int = 5,
    ) -> list["CycleBreakRule"]:
        """Detect repeated identical tool calls and consolidate per signature.

        Groups all tool_call steps by their (tool_name, serialised_input)
        signature.  For any signature that appears more than once, emits a
        single consolidated CycleBreakRule reporting the earliest step, the
        latest step, the total repetition count, and the step span.

        Args:
            trajectory: The full trajectory to analyse.
            horizon: Legacy parameter retained for API compatibility.
                The reported horizon is now the actual step span between
                the first and last occurrence of the repeated call.

        Returns:
            One rule per unique call signature that appeared more than once.
        """
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]

        # Group step indices by call signature.
        signature_steps: dict[tuple[str, str], list[int]] = defaultdict(list)
        for step in tool_calls:
            key = tool_call_signature(step)
            signature_steps[key].append(step.index)

        rules: list[CycleBreakRule] = []
        for (tool_name, _sig), step_indices in signature_steps.items():
            if len(step_indices) < 2:
                continue
            first_step = step_indices[0]
            last_step = step_indices[-1]
            span = last_step - first_step
            rules.append(
                cls(
                    id=f"cycle_{tool_name}_{first_step}_{last_step}",
                    step_index=last_step,
                    prior_step=first_step,
                    repeated_tool_name=tool_name,
                    horizon=span,
                    repetition_count=len(step_indices),
                )
            )

        return rules
