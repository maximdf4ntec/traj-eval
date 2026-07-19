"""Rule c — Tool Sequence Dependency.

For every tool_result step R that bridges a preceding call A and a following
call B, two ToolSequenceRule instances are emitted:

* polarity=positive — B is valid after A succeeded.
* polarity=negative — B must NOT be called after A failed.
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
from trajectory_eval.generator.rules._helpers import (
    next_tool_call,
    preceding_tool_call,
)


class ToolSequenceRule(HardRule):
    """Rule c: tool B may only follow tool A given A's result status.

    One instance is created per polarity per A-result-B triple found in the
    trajectory.  The ``polarity`` field distinguishes the positive (enforce
    ordering from a successful run) from the negative (block B when A failed)
    variant.

    Attributes:
        tool_a_name: Name of tool A (the prerequisite call).
        tool_a_step: Step index of tool A.
        tool_b_name: Name of tool B (the dependent call).
        result_step: Step index of the tool_result between A and B.
    """

    # Rule-specific typed fields.
    tool_a_name: str
    tool_a_step: int
    tool_b_name: str
    result_step: int

    # Class-level defaults for base Rule fields (polarity is NOT defaulted —
    # it must be supplied at construction time to distinguish variants).
    scope: RuleScope = RuleScope.frame
    step_type: Optional[StepType] = StepType.tool_call
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    # Derived text fields.
    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "ToolSequenceRule":
        """Compute rule_description and pseudocode based on polarity."""
        if self.polarity == RulePolarity.positive:
            self.rule_description = (
                f"Tool '{self.tool_b_name}' at step {self.step_index} may only be "
                f"called after '{self.tool_a_name}' (step {self.tool_a_step}) has "
                f"been successfully executed."
            )
        else:
            self.rule_description = (
                f"Tool '{self.tool_b_name}' at step {self.step_index} must NOT be "
                f"called when '{self.tool_a_name}' (step {self.tool_a_step}) failed "
                f"(tool_status != 'success')."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the sequence-dependency assertion pseudocode.

        Returns:
            Assertion string for the positive or negative variant.
        """
        if self.polarity == RulePolarity.positive:
            return (
                f"step[{self.result_step}].tool_status == 'success'"
                f" => step[{self.step_index}].tool_name == '{self.tool_b_name}'"
                f" is valid"
            )
        return (
            f"step[{self.result_step}].tool_status != 'success'"
            f" => step[{self.step_index}].tool_name != '{self.tool_b_name}'"
        )

    @classmethod
    def from_trajectory(cls, trajectory: Trajectory) -> list["ToolSequenceRule"]:
        """Build positive + negative sequence rules for every A-result-B triple.

        Args:
            trajectory: The full trajectory to analyse.

        Returns:
            Two ToolSequenceRule instances per triple (positive, then negative).
        """
        steps = trajectory.steps
        rules: list[ToolSequenceRule] = []

        for result in steps:
            if result.step_type != StepType.tool_result:
                continue
            a_call = preceding_tool_call(steps, result.index)
            b_call = next_tool_call(steps, result.index)
            if a_call is None or b_call is None:
                continue

            shared = dict(
                tool_a_name=a_call.tool_name or "",
                tool_a_step=a_call.index,
                tool_b_name=b_call.tool_name or "",
                result_step=result.index,
                step_index=b_call.index,
            )
            rules.append(
                cls(
                    id=f"tool_seq_pos_{b_call.index}",
                    polarity=RulePolarity.positive,
                    **shared,
                )
            )
            rules.append(
                cls(
                    id=f"tool_seq_neg_{b_call.index}",
                    polarity=RulePolarity.negative,
                    **shared,
                )
            )

        return rules
