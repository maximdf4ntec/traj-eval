"""Rule f — Token-to-Step Efficiency Ceiling.

For every consecutive pair of llm_response steps with non-zero token counts,
a rule asserts that the ratio token_count[N] / token_count[N-1] stays below
*max_growth_ratio*.  Exponential growth signals prompt injection or context
stuffing.

Only steps with non-zero token_count participate.  If token metadata is not
present in the trajectory (all zeros), no rules are emitted.
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


class TokenEfficiencyRule(HardRule):
    """Rule f: token growth between consecutive llm_response steps must stay bounded.

    Attributes:
        prev_step: Step index of the preceding llm_response.
        prev_token_count: Token count at the preceding step.
        curr_token_count: Token count at this step (``step_index``).
        max_growth_ratio: Maximum allowed ratio curr / prev.
        observed_ratio: Observed ratio curr / prev.
    """

    # Rule-specific typed fields.
    prev_step: int
    prev_token_count: int
    curr_token_count: int
    max_growth_ratio: float
    observed_ratio: float

    # Class-level defaults.
    polarity: RulePolarity = RulePolarity.positive
    scope: RuleScope = RuleScope.frame
    step_type: Optional[StepType] = StepType.llm_response
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    # Derived text fields.
    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "TokenEfficiencyRule":
        """Compute rule_description and pseudocode from typed fields."""
        self.rule_description = (
            f"Token count at step {self.step_index} ({self.curr_token_count}) "
            f"must not exceed {self.max_growth_ratio}x the count at step "
            f"{self.prev_step} ({self.prev_token_count}). "
            f"Observed ratio: {self.observed_ratio:.2f}."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the token-growth-ratio assertion pseudocode.

        Returns:
            Assertion string comparing the observed ratio to the ceiling.
        """
        return (
            f"step[{self.step_index}].token_count"
            f" / step[{self.prev_step}].token_count"
            f" <= {self.max_growth_ratio}"
            f"  # observed: {self.observed_ratio:.2f}"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        max_growth_ratio: float = 2.0,
    ) -> list["TokenEfficiencyRule"]:
        """Build token-efficiency rules for consecutive llm_response step pairs.

        Args:
            trajectory: The full trajectory to analyse.
            max_growth_ratio: Maximum allowed token-count growth ratio.

        Returns:
            One rule per consecutive pair of token-bearing llm_response steps.
        """
        llm_steps = [
            s
            for s in trajectory.steps
            if s.step_type == StepType.llm_response and s.token_count > 0
        ]
        rules: list[TokenEfficiencyRule] = []

        for i in range(1, len(llm_steps)):
            prev = llm_steps[i - 1]
            curr = llm_steps[i]
            ratio = curr.token_count / prev.token_count
            rules.append(
                cls(
                    id=f"token_eff_{curr.index}",
                    step_index=curr.index,
                    prev_step=prev.index,
                    prev_token_count=prev.token_count,
                    curr_token_count=curr.token_count,
                    max_growth_ratio=max_growth_ratio,
                    observed_ratio=ratio,
                )
            )

        return rules
