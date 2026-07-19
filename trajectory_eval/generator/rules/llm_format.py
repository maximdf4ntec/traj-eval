"""Rule l — LLM Response Format / Schema Conformance.

When a preceding user message explicitly requests output in a structured
format (JSON, YAML, or XML) the corresponding ``llm_response`` step must
contain a parseable document of that format.

Detection is heuristic: the prompt is scanned for case-insensitive format
keywords.  The first format keyword found wins.

Supported formats
-----------------
* ``json`` — validated with :func:`json.loads`
* ``yaml`` — validated with :func:`yaml.safe_load`
* ``xml``  — validated with :class:`xml.etree.ElementTree`
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType, Trajectory

# Regex patterns keyed by format name.  Checked in insertion order (JSON first).
_FORMAT_PATTERNS: dict[str, re.Pattern[str]] = {
    "json": re.compile(r"\bjson\b", re.IGNORECASE),
    "yaml": re.compile(r"\byaml\b", re.IGNORECASE),
    "xml": re.compile(r"\bxml\b", re.IGNORECASE),
}

_MIN_RESPONSE_LEN = 2


def _detect_requested_format(prompt: str) -> Optional[str]:
    """Return the first format keyword found in *prompt*, or ``None``.

    Args:
        prompt: The user message text to scan.

    Returns:
        One of ``"json"``, ``"yaml"``, ``"xml"``, or ``None``.
    """
    for fmt, pattern in _FORMAT_PATTERNS.items():
        if pattern.search(prompt):
            return fmt
    return None


def _is_valid_for_format(response: str, fmt: str) -> bool:
    """Check whether *response* is a valid document for *fmt*.

    Args:
        response: The LLM response text.
        fmt: One of ``"json"``, ``"yaml"``, ``"xml"``.

    Returns:
        ``True`` when the response parses cleanly for the given format.
    """
    text = response.strip()
    if fmt == "json":
        try:
            json.loads(text)
            return True
        except (json.JSONDecodeError, ValueError):
            return False
    if fmt == "yaml":
        try:
            import yaml  # noqa: PLC0415 — local import keeps module light

            yaml.safe_load(text)
            return True
        except Exception:  # noqa: BLE001
            return False
    if fmt == "xml":
        try:
            ET.fromstring(text)
            return True
        except ET.ParseError:
            return False
    return False


class LlmResponseFormatRule(HardRule):
    """Rule l: LLM response must be valid for the format requested in the prompt.

    ``polarity`` is ``positive`` when the reference response parses correctly
    for the requested format and ``negative`` when it does not (violation).

    Attributes:
        requested_format: Format detected from the preceding prompt
            (``"json"``, ``"yaml"``, or ``"xml"``).
        prompt_step_index: Step index of the user_message that requested the format.
        is_valid: Whether the response actually parses for the requested format.
    """

    requested_format: str
    prompt_step_index: int
    is_valid: bool

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = StepType.llm_response
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "LlmResponseFormatRule":
        """Derive rule_description, pseudocode, and polarity from typed fields."""
        fmt_upper = self.requested_format.upper()
        if self.is_valid:
            self.polarity = RulePolarity.positive
            self.rule_description = (
                f"LLM response at step {self.step_index} must be valid "
                f"{fmt_upper} (requested by prompt at step "
                f"{self.prompt_step_index})."
            )
        else:
            self.polarity = RulePolarity.negative
            self.confidence = ConfidenceLevel.high
            self.rule_description = (
                f"VIOLATION: LLM response at step {self.step_index} was expected "
                f"to be valid {fmt_upper} (requested by prompt at step "
                f"{self.prompt_step_index}) but failed to parse."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the format-conformance assertion pseudocode."""
        return (
            f"is_valid_{self.requested_format}(step[{self.step_index}].response)"
            f"  # format requested at step {self.prompt_step_index}"
        )

    @classmethod
    def from_trajectory(cls, trajectory: Trajectory) -> list["LlmResponseFormatRule"]:
        """Build format rules for llm_response steps whose prompt requests a format.

        For each ``llm_response`` step the generator searches backward for the
        most recent ``user_message`` step and scans its prompt for format
        keywords.  A rule is generated only when a keyword is found.

        Args:
            trajectory: The full trajectory to analyse.

        Returns:
            One LlmResponseFormatRule per llm_response step with a detectable
            format request in its preceding user message.
        """
        steps = trajectory.steps
        rules: list[LlmResponseFormatRule] = []

        for step in steps:
            if step.step_type != StepType.llm_response:
                continue
            response = step.response or ""
            if len(response.strip()) < _MIN_RESPONSE_LEN:
                continue

            # Find the most recent user_message step before this llm_response.
            prompt_step: Optional[Step] = None
            for s in reversed(steps):
                if s.index < step.index and s.step_type == StepType.user_message:
                    prompt_step = s
                    break

            if prompt_step is None or not prompt_step.prompt:
                continue

            fmt = _detect_requested_format(prompt_step.prompt)
            if fmt is None:
                continue

            is_valid = _is_valid_for_format(response, fmt)

            rules.append(
                cls(
                    id=f"llm_format_{step.index}_{fmt}",
                    step_index=step.index,
                    requested_format=fmt,
                    prompt_step_index=prompt_step.index,
                    is_valid=is_valid,
                    polarity=RulePolarity.positive,  # overridden by model_validator
                )
            )

        return rules
