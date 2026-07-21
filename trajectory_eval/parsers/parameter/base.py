"""ParameterParser abstract base class.

Follows the same ABC + BaseModel pattern used by the Rule hierarchy
(see trajectory_eval/models/rule.py).  Each concrete parser subclass
identifies a single ParameterType it handles and implements detection
(can_parse) and decomposition (parse) logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from trajectory_eval.models.tool import ParameterType, ToolParameter


class ParameterParser(BaseModel, ABC):
    """Abstract base for all parameter parsers.

    Subclasses must:
    1. Set ``parameter_type`` to the :class:`ParameterType` they handle.
    2. Implement :meth:`can_parse` to detect whether a raw value matches.
    3. Implement :meth:`parse` to decompose the value into a
       :class:`ToolParameter` with populated ``sub_parameters``.

    The subclass decides internally whether to recurse into nested content
    within subcomponents (parser-decides depth strategy, Req 5.5).
    """

    parameter_type: ParameterType
    """Class-level identifier for the ParameterType this parser handles."""

    @abstractmethod
    def can_parse(self, value: Any) -> bool:
        """Return True when *value* is recognized as this parser's target type.

        Args:
            value: The raw parameter value to inspect.

        Returns:
            True if this parser can handle the value; False otherwise.
        """
        ...

    @abstractmethod
    def parse(self, key: str, value: Any) -> ToolParameter:
        """Decompose *value* into a ToolParameter with typed sub_parameters.

        This method should only be called when :meth:`can_parse` returned True.

        Args:
            key: The original parameter name (e.g. "command", "file_text").
            value: The raw parameter value to parse.

        Returns:
            A fully populated ToolParameter instance.
        """
        ...
