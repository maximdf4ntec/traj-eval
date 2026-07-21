"""CodeParser: detects Python source code in parameter values.

Reuses the same Python-keyword heuristic as ``_is_valid_python`` in
``trajectory_eval/generator/rules/tool_result_type.py`` to maintain
detection parity between input and output typing (Req 12.2).
"""

from __future__ import annotations

import ast
from typing import Any

from trajectory_eval.models.tool import (
    ParameterType,
    SubParameter,
    ToolParameter,
)
from trajectory_eval.parsers.parameter.base import ParameterParser

# Same keyword list used by _is_valid_python in tool_result_type.py (Req 7.3).
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


class CodeParser(ParameterParser):
    """Parser that detects Python source code via keyword heuristic + AST check.

    Detection logic mirrors ``_is_valid_python`` from tool_result_type.py:
    the value must contain at least one Python keyword **and** parse
    successfully via :func:`ast.parse`.

    Produces a single SubParameter containing the full code body with
    ``detected_type=code``.
    """

    parameter_type: ParameterType = ParameterType.code

    def can_parse(self, value: Any) -> bool:
        """Return True when *value* looks like valid Python source code.

        Applies the same heuristic as ``_is_valid_python``:
        1. At least one Python keyword present in text.
        2. Text parses without SyntaxError via :func:`ast.parse`.

        Args:
            value: The raw parameter value to inspect.

        Returns:
            True if the value is a string containing Python keywords and
            valid Python syntax; False otherwise.
        """
        if not isinstance(value, str):
            return False
        if not any(kw in value for kw in _PYTHON_KEYWORDS):
            return False
        try:
            ast.parse(value)
            return True
        except SyntaxError:
            return False

    def parse(self, key: str, value: Any) -> ToolParameter:
        """Decompose a Python code value into a ToolParameter.

        Produces a ToolParameter with ``detected_type=code`` containing a
        single SubParameter named ``"code_body"`` that holds the full code
        content.

        Args:
            key: The original parameter name (e.g. "file_text").
            value: The raw Python source string.

        Returns:
            A ToolParameter with detected_type=code and one SubParameter.
        """
        return ToolParameter(
            key=key,
            raw_value=value,
            detected_type=ParameterType.code,
            sub_parameters=[
                SubParameter(
                    name="code_body",
                    value=value,
                    detected_type=ParameterType.code,
                ),
            ],
        )
