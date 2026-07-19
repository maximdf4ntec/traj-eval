"""Rule k — Tool Result Output Type Validation.

For each ``tool_result`` step the rule detects the content type of the
output (JSON, XML, Python code, or a plain number) and asserts that the
content is valid for that type.

Detection priority
------------------
1. Tool-name hint  — if the tool name contains a format keyword (e.g. ``"json"``)
2. Content-based   — try JSON → XML → Python (with keyword guard) → number

Plain-text output is skipped (no useful structural validation).
"""

from __future__ import annotations

import ast
import json
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType, Trajectory

# Tool-name substrings that hint at JSON output.
_JSON_TOOL_HINTS: frozenset[str] = frozenset(["json"])

# Python keywords that guard against false positives in content detection.
_PYTHON_KEYWORDS: tuple[str, ...] = (
    "def ",
    "class ",
    "import ",
    "from ",
    "async def ",
    "if __name__",
    "@",
    "return ",
    "yield ",
)

_MIN_CONTENT_LEN = 4


class OutputType(str, Enum):
    """Detected structured content type of a tool_result output.

    Attributes:
        json: Valid JSON (object or array).
        xml: Valid XML document.
        python: Valid Python source code with at least one Python keyword.
        number: A single numeric value (int or float).
    """

    json = "json"
    xml = "xml"
    python = "python"
    number = "number"


def _is_valid_json(text: str) -> bool:
    """Return True when *text* is parseable JSON starting with ``{`` or ``[``."""
    stripped = text.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return False
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _is_valid_xml(text: str) -> bool:
    """Return True when *text* is a parseable XML document."""
    stripped = text.strip()
    if not stripped.startswith("<"):
        return False
    try:
        ET.fromstring(stripped)
        return True
    except ET.ParseError:
        return False


def _is_valid_python(text: str) -> bool:
    """Return True when *text* is valid Python source containing Python keywords."""
    if not any(kw in text for kw in _PYTHON_KEYWORDS):
        return False
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        return False


def _is_number(text: str) -> bool:
    """Return True when stripped *text* is a single int or float."""
    stripped = text.strip()
    if "\n" in stripped or " " in stripped:
        return False
    try:
        float(stripped)
        return True
    except ValueError:
        return False


def _detect_output_type(
    tool_name: str,
    content: str,
) -> Optional[tuple[OutputType, str]]:
    """Detect the structured content type of a tool_result output.

    Applies tool-name hints first, then falls back to content-based probes.

    Args:
        tool_name: Name of the tool that produced *content*.
        content: Raw tool_result output text.

    Returns:
        A ``(OutputType, detection_method)`` tuple, or ``None`` for plain text.
        ``detection_method`` is one of ``"tool_name_hint"`` or
        ``"content_detection"``.
    """
    name_lower = tool_name.lower()
    content_stripped = content.strip()

    # Tool-name hints take highest priority.
    if any(hint in name_lower for hint in _JSON_TOOL_HINTS):
        if _is_valid_json(content_stripped):
            return OutputType.json, "tool_name_hint"

    # Content-based probes ordered by specificity.
    if _is_valid_json(content_stripped):
        return OutputType.json, "content_detection"
    if _is_valid_xml(content_stripped):
        return OutputType.xml, "content_detection"
    if _is_valid_python(content_stripped):
        return OutputType.python, "content_detection"
    if _is_number(content_stripped):
        return OutputType.number, "content_detection"

    return None  # plain text — skip


_VALIDATORS: dict[OutputType, "Callable[[str], bool]"] = {  # type: ignore[name-defined]
    OutputType.json: _is_valid_json,
    OutputType.xml: _is_valid_xml,
    OutputType.python: _is_valid_python,
    OutputType.number: _is_number,
}


class ToolResultTypeRule(HardRule):
    """Rule k: tool_result output must remain valid for its detected type.

    ``polarity`` is ``positive`` when the reference output is valid for the
    detected type (expected case) and ``negative`` when it is not (violation).

    Attributes:
        tool_name: Name of the tool that produced this result.
        detected_type: The structured type inferred for this output.
        detection_method: ``"tool_name_hint"`` or ``"content_detection"``.
        is_valid: Whether the reference output validates for the detected type.
    """

    tool_name: str
    detected_type: OutputType
    detection_method: str
    is_valid: bool

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = StepType.tool_result
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "ToolResultTypeRule":
        """Derive rule_description, pseudocode, and polarity from typed fields."""
        type_label = self.detected_type.value.upper()
        if self.is_valid:
            self.polarity = RulePolarity.positive
            self.rule_description = (
                f"Tool '{self.tool_name}' result at step {self.step_index} must "
                f"be valid {type_label} "
                f"(detected via {self.detection_method})."
            )
        else:
            self.polarity = RulePolarity.negative
            self.confidence = ConfidenceLevel.high
            self.rule_description = (
                f"VIOLATION: Tool '{self.tool_name}' result at step "
                f"{self.step_index} was expected to be valid {type_label} "
                f"(detected via {self.detection_method}) but failed validation."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the output-type validation assertion pseudocode."""
        return (
            f"is_valid_{self.detected_type.value}(step[{self.step_index}].tool_output)"
            f"  # tool={self.tool_name!r}, detected_via={self.detection_method}"
        )

    @classmethod
    def from_trajectory(cls, trajectory: Trajectory) -> list["ToolResultTypeRule"]:
        """Build output-type rules for all tool_result steps with detectable types.

        Args:
            trajectory: The full trajectory to analyse.

        Returns:
            One ToolResultTypeRule per tool_result step whose output has a
            detectable structured type (JSON, XML, Python, or number).
        """
        steps = trajectory.steps
        rules: list[ToolResultTypeRule] = []

        for step in steps:
            if step.step_type != StepType.tool_result:
                continue
            output = step.tool_output or ""
            if len(output.strip()) < _MIN_CONTENT_LEN:
                continue

            # Retrieve the preceding tool_call to get the tool-name hint.
            tool_name = ""
            for s in reversed(steps):
                if s.index < step.index and s.step_type == StepType.tool_call:
                    tool_name = s.tool_name or ""
                    break

            detection = _detect_output_type(tool_name, output)
            if detection is None:
                continue

            detected_type, method = detection
            is_valid = _VALIDATORS[detected_type](output.strip())

            rules.append(
                cls(
                    id=f"tool_result_type_{step.index}",
                    step_index=step.index,
                    tool_name=tool_name,
                    detected_type=detected_type,
                    detection_method=method,
                    is_valid=is_valid,
                    polarity=RulePolarity.positive,  # overridden by model_validator
                )
            )

        return rules
