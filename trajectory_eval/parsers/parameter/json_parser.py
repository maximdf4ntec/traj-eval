"""JsonParser — detects valid JSON strings and exposes top-level structure.

Detection logic reuses the same structural check as ``_is_valid_json`` from
``trajectory_eval/generator/rules/tool_result_type.py``: the value must be a
string that starts with ``{`` or ``[`` (after stripping) and successfully
parses via ``json.loads``.

For JSON objects, one SubParameter is produced per top-level key.
For JSON arrays, one SubParameter per element with name ``element_{index}``.
"""

from __future__ import annotations

import json
from typing import Any

from trajectory_eval.models.tool import (
    ParameterType,
    SubParameter,
    ToolParameter,
)
from trajectory_eval.parsers.parameter.base import ParameterParser


def _is_valid_json(text: str) -> bool:
    """Return True when *text* is parseable JSON starting with ``{`` or ``[``.

    This replicates the logic from ``tool_result_type._is_valid_json`` to
    maintain detection parity (Requirement 12.1).
    """
    stripped = text.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return False
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


class JsonParser(ParameterParser):
    """Detects valid JSON strings and exposes top-level structure as SubParameters.

    For JSON objects: one SubParameter per top-level key (name=key, value=val).
    For JSON arrays: one SubParameter per element (name=element_{i}, value=element).

    All SubParameters have ``detected_type=plain_text`` and empty
    ``sub_parameters`` (no recursive type-detection of nested values).
    """

    parameter_type: ParameterType = ParameterType.json

    def can_parse(self, value: Any) -> bool:
        """Return True when *value* is a valid JSON object or array string.

        Validates:
            - Requirement 9.1: valid JSON (object or array) → True
            - Requirement 12.1: same structural check as _is_valid_json
        """
        if not isinstance(value, str):
            return False
        return _is_valid_json(value)

    def parse(self, key: str, value: Any) -> ToolParameter:
        """Decompose a JSON string into a ToolParameter with sub_parameters.

        For JSON objects: one SubParameter per top-level key.
        For JSON arrays: one SubParameter per element with name ``element_{i}``.

        Validates:
            - Requirement 9.2: JSON object → one SubParameter per top-level key
            - Requirement 9.3: JSON array → SubParameters named element_{index}

        Args:
            key: The original parameter name.
            value: The raw JSON string to parse.

        Returns:
            A ToolParameter with detected_type=json and populated sub_parameters.
        """
        parsed = json.loads(value.strip())
        sub_parameters: list[SubParameter] = []

        if isinstance(parsed, dict):
            for k, v in parsed.items():
                sub_parameters.append(
                    SubParameter(
                        name=k,
                        value=v,
                        detected_type=ParameterType.plain_text,
                        sub_parameters=[],
                    )
                )
        elif isinstance(parsed, list):
            for i, element in enumerate(parsed):
                sub_parameters.append(
                    SubParameter(
                        name=f"element_{i}",
                        value=element,
                        detected_type=ParameterType.plain_text,
                        sub_parameters=[],
                    )
                )

        return ToolParameter(
            key=key,
            raw_value=value,
            detected_type=ParameterType.json,
            sub_parameters=sub_parameters,
        )
