"""ParserRegistry: ordered-priority dispatch for parameter type detection.

Iterates registered parsers in order; the first whose ``can_parse`` returns
True wins.  Non-string values are handled inline (int/float → number,
otherwise plain_text).  When no parser matches a string value, the registry
falls back to ``ToolParameter(detected_type=plain_text, sub_parameters=[])``.
"""

from __future__ import annotations

import logging
from typing import Any

from trajectory_eval.models.tool import ParameterType, ToolParameter
from trajectory_eval.parsers.parameter.base import ParameterParser

logger = logging.getLogger(__name__)


def _detect_non_string(value: Any) -> ParameterType:
    """Determine the ParameterType for a non-string value.

    - bool → ParameterType.boolean
    - int/float → ParameterType.number
    - All other non-string types (list, dict, None, etc.) → ParameterType.plain_text
    """
    if isinstance(value, bool):
        return ParameterType.boolean
    if isinstance(value, (int, float)):
        return ParameterType.number
    return ParameterType.plain_text


class ParserRegistry:
    """Ordered-priority dispatch. First parser whose ``can_parse`` returns True wins.

    Attributes:
        _parsers: The ordered list of ParameterParser instances consulted
                  from first to last for each parameter value.
    """

    def __init__(self, parsers: list[ParameterParser] | None = None) -> None:
        self._parsers: list[ParameterParser] = (
            parsers if parsers is not None else self._default_order()
        )

    @staticmethod
    def _default_order() -> list[ParameterParser]:
        """Return the default parser ordering.

        Default order (most specific to least specific for string values):
        UrlParser, CommandLineParser, JsonParser, CodeParser, PathParser.

        UrlParser is first because URLs are unambiguous (http:// or https://
        prefix) and should not be misclassified as command lines or paths.

        Uses lazy imports to avoid circular dependencies.
        """
        from trajectory_eval.parsers.parameter.url import UrlParser
        from trajectory_eval.parsers.parameter.command_line import CommandLineParser
        from trajectory_eval.parsers.parameter.json_parser import JsonParser
        from trajectory_eval.parsers.parameter.code import CodeParser
        from trajectory_eval.parsers.parameter.path import PathParser

        return [
            UrlParser(),
            CommandLineParser(),
            JsonParser(),
            CodeParser(),
            PathParser(),
        ]

    def detect(self, key: str, value: Any) -> ToolParameter:
        """Dispatch *value* to the first matching parser, or return plain_text.

        For non-string values, no parser is consulted; the type is determined
        by :func:`_detect_non_string`.

        Args:
            key: The original parameter name.
            value: The raw parameter value to detect.

        Returns:
            A ToolParameter with the detected type and any sub_parameters
            populated by the winning parser.
        """
        if not isinstance(value, str):
            return ToolParameter(
                key=key,
                raw_value=value,
                detected_type=_detect_non_string(value),
            )

        for parser in self._parsers:
            try:
                if parser.can_parse(value):
                    return parser.parse(key, value)
            except Exception:  # noqa: BLE001
                # Parser error during can_parse or parse — fall through to next
                logger.debug(
                    "Parser %s raised an exception for key=%r; skipping.",
                    type(parser).__name__,
                    key,
                    exc_info=True,
                )
                continue

        return ToolParameter(
            key=key,
            raw_value=value,
            detected_type=ParameterType.plain_text,
        )

    def insert(self, index: int, parser: ParameterParser) -> None:
        """Insert a parser at the given position in the priority list.

        This allows extending the registry without modifying existing parser
        implementations (Req 10.4).

        Args:
            index: Position at which to insert (0 = highest priority).
            parser: The ParameterParser instance to add.
        """
        self._parsers.insert(index, parser)
