"""Per-step token budget enforcement rule.

For each step in a trajectory with a positive ``token_count``, this rule
asserts that the step's token consumption does not exceed the observed value
plus a configurable percentage budget.

Example:
    If ``token_count`` is 500 and ``token_budget_pct`` is 20.0, the threshold
    is ``500 * 1.2 = 600``.  The generated assertion is
    ``step[N].token_count <= 600``.
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


class TokenBudgetRule(HardRule):
    """Per-step token budget enforcement rule.

    Attributes:
        observed_tokens: Token count observed in the reference step.
        threshold_tokens: Maximum allowed token count (inclusive).
        token_budget_pct: Percentage above observed that defines the threshold.
    """

    observed_tokens: int
    threshold_tokens: float
    token_budget_pct: float

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = None
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "TokenBudgetRule":
        self.polarity = RulePolarity.positive
        self.rule_description = (
            f"Step {self.step_index} token_count must not exceed "
            f"{self.threshold_tokens:.0f} "
            f"(observed {self.observed_tokens} + {self.token_budget_pct}% budget)."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        return f"step[{self.step_index}].token_count <= {self.threshold_tokens:.0f}"

    @classmethod
    def from_trajectory(
        cls, trajectory: Trajectory, *, token_budget_pct: float = 20.0, **kwargs
    ) -> list["TokenBudgetRule"]:
        rules: list[TokenBudgetRule] = []
        for step in trajectory.steps:
            if step.token_count <= 0:
                continue
            threshold = step.token_count * (1 + token_budget_pct / 100)
            rules.append(
                cls(
                    id=f"token_budget_{step.index}",
                    step_index=step.index,
                    polarity=RulePolarity.positive,
                    step_type=step.step_type,
                    observed_tokens=step.token_count,
                    threshold_tokens=threshold,
                    token_budget_pct=token_budget_pct,
                )
            )
        return rules
