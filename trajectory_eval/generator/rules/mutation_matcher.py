"""Rule g — Environment Mutation Matcher.

If a tool_result step reports failure or an empty state, the agent's next
tool_call must differ from the failed call.  An identical retry with the
same tool and inputs violates this rule (no adaptation observed).
"""

from __future__ import annotations

import json
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
    failed_step_indices,
    is_empty_step,
    next_tool_call,
    preceding_tool_call,
)

_DEFAULT_FAILURE_KEYWORDS: frozenset[str] = frozenset(
    [
        "error",
        "exception",
        "failed",
        "traceback",
        "stderr",
        "errno",
        "no such file",
        "permission denied",
        "timeout",
        "not found",
    ]
)


class MutationMatcherRule(HardRule):
    """Rule g: the agent must adapt its next call after a failed/empty result.

    Attributes:
        failure_step: Step index of the failed or empty tool_result.
        failed_call_step: Step index of the call that produced the failure.
        adapted: True when the subsequent call differs from the failed call.
    """

    # Rule-specific typed fields.
    failure_step: int
    failed_call_step: int
    adapted: bool
    failed_tool_name: str = ""

    # Class-level defaults.
    polarity: RulePolarity = RulePolarity.negative
    scope: RuleScope = RuleScope.frame
    step_type: Optional[StepType] = StepType.tool_call
    # Confidence is high when a violation is detected, medium otherwise.
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    # Derived text fields.
    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "MutationMatcherRule":
        """Compute rule_description, pseudocode, and confidence from typed fields."""
        if not self.adapted:
            self.confidence = ConfidenceLevel.high
            suffix = "VIOLATION: identical call repeated -- no adaptation."
        else:
            suffix = "Agent adapted with a different tool or arguments."
        self.rule_description = (
            f"After failure at step {self.failure_step}, the agent's next action "
            f"(step {self.step_index}) must differ from the failed call "
            f"(step {self.failed_call_step}). {suffix}"
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the adaptation-requirement assertion pseudocode.

        Returns:
            Assertion string requiring the next call to differ from the failed one.
        """
        return (
            f"step[{self.step_index}] != step[{self.failed_call_step}]"
            f"  # must adapt after failure at step {self.failure_step}"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        failure_keywords: Optional[list[str]] = None,
    ) -> list["MutationMatcherRule"]:
        """Build mutation-matcher rules for every failed/empty tool_result.

        A tool_result is considered failed only when there is structural
        evidence: an adjacent StepType.error step following the tool_result.
        Naive keyword matching (e.g. "error" in output) is not used because
        it produces false positives when outputs incidentally contain those
        words in file paths, source code, or documentation text.

        Empty results (null, {}, [], or blank) are still detected via
        is_empty_step as they represent a structural signal.

        Args:
            trajectory: The full trajectory to analyse.
            failure_keywords: Ignored (kept for API compatibility). Failure
                detection now uses structural StepType.error steps only.

        Returns:
            One rule per failed/empty tool_result that has a subsequent call.
        """
        steps = trajectory.steps
        rules: list[MutationMatcherRule] = []

        # Identify tool_result steps that are structurally failed (followed
        # by a StepType.error step).
        structurally_failed = failed_step_indices(steps)

        for step in steps:
            if step.step_type != StepType.tool_result:
                continue
            # Only consider structurally-failed steps or empty results.
            is_structural_failure = step.index in structurally_failed
            if not (is_structural_failure or is_empty_step(step)):
                continue
            call_before = preceding_tool_call(steps, step.index)
            call_after = next_tool_call(steps, step.index)
            if call_before is None or call_after is None:
                continue

            before_sig = (
                json.dumps(call_before.tool_input, sort_keys=True)
                if call_before.tool_input
                else "null"
            )
            after_sig = (
                json.dumps(call_after.tool_input, sort_keys=True)
                if call_after.tool_input
                else "null"
            )
            identical = (
                call_before.tool_name == call_after.tool_name
                and before_sig == after_sig
            )

            rules.append(
                cls(
                    id=f"mutation_{call_after.index}",
                    step_index=call_after.index,
                    failure_step=step.index,
                    failed_call_step=call_before.index,
                    adapted=not identical,
                    failed_tool_name=call_before.tool_name or "",
                )
            )

        return rules
