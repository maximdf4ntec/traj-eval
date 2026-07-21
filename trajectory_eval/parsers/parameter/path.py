"""PathParser — detects Unix and Windows absolute file paths.

Detection logic is consistent with ``_is_file_path_output`` from
``trajectory_eval/generator/rules/tool_result_type.py``, adapted for
single parameter values rather than multi-line tool output.
"""

from __future__ import annotations

import re
from typing import Any

from trajectory_eval.models.tool import ParameterType, ToolParameter
from trajectory_eval.parsers.parameter.base import ParameterParser

# Unix absolute path: starts with /, contains path segments separated by /,
# and ends with an extension (1-10 alpha chars after the last dot).
_RE_UNIX_PATH = re.compile(r"^/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10}$")

# Windows absolute path: starts with a drive letter followed by :\
_RE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:\\")


def _is_file_path(value: str) -> bool:
    """Return True when *value* looks like a single file-system path.

    Consistent with the multi-line ``_is_file_path_output`` helper but
    operating on a single trimmed string (one path, no newlines expected).
    """
    stripped = value.strip()
    if not stripped:
        return False

    # Reject multi-line values — PathParser handles single paths.
    if "\n" in stripped:
        return False

    # Unix absolute path
    if stripped.startswith("/"):
        return bool(_RE_UNIX_PATH.match(stripped))

    # Windows absolute path (drive letter + :\)
    if _RE_WINDOWS_PATH.match(stripped):
        # Must contain at least one backslash separator (already guaranteed
        # by the drive letter pattern) and have path-like content.
        return "\\" in stripped
    return False


class PathParser(ParameterParser):
    """Detects Unix and Windows absolute file paths.

    Produces a ToolParameter with ``detected_type=file_path`` and empty
    ``sub_parameters`` — paths are atomic values with no internal structure
    that needs decomposition.
    """

    parameter_type: ParameterType = ParameterType.file_path

    def can_parse(self, value: Any) -> bool:
        """Return True when *value* is a Unix or Windows absolute path.

        Validates:
            - Requirement 8.1: Unix absolute paths (starts with /, extension)
            - Requirement 8.2: Windows absolute paths (drive letter + :\\)
            - Requirement 12.3: Consistent with _is_file_path_output
        """
        if not isinstance(value, str):
            return False
        return _is_file_path(value)

    def parse(self, key: str, value: Any) -> ToolParameter:
        """Return a ToolParameter with detected_type=file_path, empty sub_parameters.

        Validates:
            - Requirement 8.3: detected_type=file_path, empty sub_parameters
        """
        return ToolParameter(
            key=key,
            raw_value=value,
            detected_type=ParameterType.file_path,
            sub_parameters=[],
        )
