"""Per-step latency budget enforcement rule.

Generates one ``LatencyBudgetRule`` for each trajectory step whose
``latency_ms`` is greater than zero.  The rule asserts that the step's
latency does not exceed a configurable percentage above the observed value.
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


class LatencyBudgetRule(HardRule):
    """Per-step latency budget enforcement rule.

    Attributes:
        observed_latency_ms: Latency observed in the reference step.
        threshold_latency_ms: Maximum allowed latency (inclusive).
        latency_budget_pct: Percentage above observed that defines the threshold.
    """

    observed_latency_ms: int
    threshold_latency_ms: float
    latency_budget_pct: float

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = None
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "LatencyBudgetRule":
        self.polarity = RulePolarity.positive
        self.rule_description = (
            f"Step {self.step_index} latency_ms must not exceed "
            f"{self.threshold_latency_ms:.0f} "
            f"(observed {self.observed_latency_ms} + {self.latency_budget_pct}% budget)."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        return f"step[{self.step_index}].latency_ms <= {self.threshold_latency_ms:.0f}"

    @classmethod
    def from_trajectory(
        cls, trajectory: Trajectory, *, latency_budget_pct: float = 50.0, **kwargs
    ) -> list["LatencyBudgetRule"]:
        rules: list[LatencyBudgetRule] = []
        for step in trajectory.steps:
            if step.latency_ms <= 0:
                continue
            threshold = step.latency_ms * (1 + latency_budget_pct / 100)
            rules.append(
                cls(
                    id=f"latency_budget_{step.index}",
                    step_index=step.index,
                    polarity=RulePolarity.positive,
                    step_type=step.step_type,
                    observed_latency_ms=step.latency_ms,
                    threshold_latency_ms=threshold,
                    latency_budget_pct=latency_budget_pct,
                )
            )
        return rules
