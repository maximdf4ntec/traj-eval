"""Rule j — Terminal State Check.

The last meaningful (non-error) step in the trajectory must contain at
least one recognised completion keyword.  When none is found the rule is
flagged as a violation.
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
from trajectory_eval.models.trajectory import Step, StepType, Trajectory

_DEFAULT_COMPLETION_KEYWORDS: tuple[str, ...] = (
    "done",
    "complete",
    "completed",
    "finished",
    "fixed",
    "resolved",
    "success",
    "successfully",
    "all tests pass",
    "implemented",
    "applied",
    "submit",
    "submitted",
)


def _step_text(step: Step) -> str:
    """Return the primary text content of any step type.

    Args:
        step: Any trajectory step.

    Returns:
        The most relevant text for the step, or an empty string.
    """
    if step.step_type == StepType.llm_response:
        return step.response or ""
    if step.step_type == StepType.tool_result:
        return step.tool_output or ""
    if step.step_type == StepType.user_message:
        return step.prompt or ""
    if step.step_type == StepType.tool_call:
        return " ".join(str(v) for v in (step.tool_input or {}).values())
    return ""


class TerminalStateRule(HardRule):
    """Rule j: the trajectory must end with a recognized completion action.

    The final non-error step's text is scanned for completion keywords.
    ``polarity`` is set to ``positive`` when a keyword is found (trajectory
    ended cleanly) and ``negative`` when none are present (violation flagged).

    Attributes:
        last_step_index: Index of the last non-error step in the trajectory.
        last_step_type: StepType of that final step.
        completion_keywords: Keywords that signal a finished trajectory.
        found_keyword: The first keyword matched; empty string when absent.
    """

    last_step_index: int
    last_step_type: StepType
    completion_keywords: list[str]
    found_keyword: str

    scope: RuleScope = RuleScope.global_
    step_type: Optional[StepType] = None
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "TerminalStateRule":
        """Derive rule_description, pseudocode, and polarity from typed fields."""
        kw_list = ", ".join(repr(k) for k in self.completion_keywords)
        if self.found_keyword:
            self.polarity = RulePolarity.positive
            self.rule_description = (
                f"The trajectory ends with a recognized completion action at step "
                f"{self.last_step_index} ({self.last_step_type.value}): "
                f"keyword {self.found_keyword!r} was found."
            )
        else:
            self.polarity = RulePolarity.negative
            self.confidence = ConfidenceLevel.high
            self.rule_description = (
                f"VIOLATION: The trajectory's last step (index {self.last_step_index}, "
                f"type {self.last_step_type.value}) contains none of the required "
                f"completion keywords: {kw_list}."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the terminal-state assertion pseudocode."""
        kw_list = ", ".join(repr(k) for k in self.completion_keywords)
        return (
            f"any(kw in _last_step_text(trajectory).lower() "
            f"for kw in [{kw_list}])"
            f"  # last_step={self.last_step_index}"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        completion_keywords: Optional[list[str]] = None,
    ) -> list["TerminalStateRule"]:
        """Generate a single terminal-state rule from the trajectory.

        Args:
            trajectory: The full trajectory.
            completion_keywords: Keywords that indicate a finished trajectory.
                Defaults to the built-in list when not provided.

        Returns:
            A list with exactly one TerminalStateRule, or an empty list when
            the trajectory has no non-error steps.
        """
        keywords: list[str] = list(
            completion_keywords
            if completion_keywords is not None
            else _DEFAULT_COMPLETION_KEYWORDS
        )

        last_step: Optional[Step] = None
        for step in reversed(trajectory.steps):
            if step.step_type != StepType.error:
                last_step = step
                break

        if last_step is None:
            return []

        text = _step_text(last_step).lower()
        found = next((kw for kw in keywords if kw.lower() in text), "")

        return [
            cls(
                id=f"terminal_state_{last_step.index}",
                step_index=last_step.index,
                last_step_index=last_step.index,
                last_step_type=last_step.step_type,
                completion_keywords=keywords,
                found_keyword=found,
                polarity=RulePolarity.positive,  # overridden by model_validator
            )
        ]
