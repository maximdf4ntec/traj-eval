"""Unit tests for ParserRegistry."""

from __future__ import annotations

from typing import Any

import pytest

from trajectory_eval.models.tool import ParameterType, ToolParameter
from trajectory_eval.parsers.parameter.base import ParameterParser
from trajectory_eval.parsers.parameter.registry import (
    ParserRegistry,
    _detect_non_string,
)


# --- Helpers / Fakes ---


class AlwaysMatchParser(ParameterParser):
    """A parser that matches every string value."""

    parameter_type: ParameterType = ParameterType.json

    def can_parse(self, value: Any) -> bool:
        return True

    def parse(self, key: str, value: Any) -> ToolParameter:
        return ToolParameter(
            key=key, raw_value=value, detected_type=self.parameter_type
        )


class NeverMatchParser(ParameterParser):
    """A parser that never matches."""

    parameter_type: ParameterType = ParameterType.code

    def can_parse(self, value: Any) -> bool:
        return False

    def parse(self, key: str, value: Any) -> ToolParameter:
        raise AssertionError("Should never be called")


class ExplodingParser(ParameterParser):
    """A parser that raises during can_parse."""

    parameter_type: ParameterType = ParameterType.xml

    def can_parse(self, value: Any) -> bool:
        raise RuntimeError("boom")

    def parse(self, key: str, value: Any) -> ToolParameter:
        raise RuntimeError("boom")


class ParseExplodingParser(ParameterParser):
    """A parser whose can_parse succeeds but parse raises."""

    parameter_type: ParameterType = ParameterType.code

    def can_parse(self, value: Any) -> bool:
        return True

    def parse(self, key: str, value: Any) -> ToolParameter:
        raise ValueError("parse failed")


# --- Tests for _detect_non_string ---


class TestDetectNonString:
    def test_integer_returns_number(self) -> None:
        assert _detect_non_string(42) == ParameterType.number

    def test_float_returns_number(self) -> None:
        assert _detect_non_string(3.14) == ParameterType.number

    def test_negative_number(self) -> None:
        assert _detect_non_string(-7) == ParameterType.number

    def test_bool_returns_boolean(self) -> None:
        # bool is a subclass of int, but we detect it as boolean
        assert _detect_non_string(True) == ParameterType.boolean
        assert _detect_non_string(False) == ParameterType.boolean

    def test_list_returns_plain_text(self) -> None:
        assert _detect_non_string([1, 2, 3]) == ParameterType.plain_text

    def test_dict_returns_plain_text(self) -> None:
        assert _detect_non_string({"a": 1}) == ParameterType.plain_text

    def test_none_returns_plain_text(self) -> None:
        assert _detect_non_string(None) == ParameterType.plain_text


# --- Tests for ParserRegistry ---


class TestParserRegistryDetect:
    def test_empty_registry_falls_back_to_plain_text(self) -> None:
        reg = ParserRegistry(parsers=[])
        result = reg.detect("key", "hello")
        assert result.key == "key"
        assert result.raw_value == "hello"
        assert result.detected_type == ParameterType.plain_text
        assert result.sub_parameters == []

    def test_first_matching_parser_wins(self) -> None:
        """Req 10.2: first matching parser in priority order is used."""
        json_parser = AlwaysMatchParser(parameter_type=ParameterType.json)
        code_parser = AlwaysMatchParser(parameter_type=ParameterType.code)
        reg = ParserRegistry(parsers=[json_parser, code_parser])

        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.json

    def test_skips_non_matching_parsers(self) -> None:
        reg = ParserRegistry(
            parsers=[
                NeverMatchParser(),
                AlwaysMatchParser(parameter_type=ParameterType.code),
            ]
        )
        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.code

    def test_non_string_int_returns_number(self) -> None:
        reg = ParserRegistry(parsers=[AlwaysMatchParser()])
        result = reg.detect("count", 10)
        assert result.detected_type == ParameterType.number
        assert result.raw_value == 10

    def test_non_string_dict_returns_plain_text(self) -> None:
        reg = ParserRegistry(parsers=[AlwaysMatchParser()])
        result = reg.detect("data", {"nested": True})
        assert result.detected_type == ParameterType.plain_text

    def test_non_string_list_returns_plain_text(self) -> None:
        reg = ParserRegistry(parsers=[AlwaysMatchParser()])
        result = reg.detect("items", [1, 2, 3])
        assert result.detected_type == ParameterType.plain_text

    def test_parser_exception_in_can_parse_is_skipped(self) -> None:
        """Parser errors fall through to the next parser."""
        reg = ParserRegistry(
            parsers=[
                ExplodingParser(),
                AlwaysMatchParser(parameter_type=ParameterType.json),
            ]
        )
        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.json

    def test_parser_exception_in_parse_is_skipped(self) -> None:
        """When parse raises, fall through to next parser."""
        reg = ParserRegistry(
            parsers=[
                ParseExplodingParser(),
                AlwaysMatchParser(parameter_type=ParameterType.json),
            ]
        )
        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.json

    def test_all_parsers_fail_falls_back_to_plain_text(self) -> None:
        reg = ParserRegistry(parsers=[ExplodingParser(), NeverMatchParser()])
        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.plain_text
        assert result.sub_parameters == []

    def test_default_registry_returns_plain_text_for_strings(self) -> None:
        """Default registry with real parsers uses first-match semantics."""
        reg = ParserRegistry()
        # "just text" matches CommandLineParser (looks like a command), so
        # detection returns command_line. For an actual plain_text result we
        # need a value that no parser matches — use an empty string.
        result = reg.detect("msg", "")
        assert result.detected_type == ParameterType.plain_text


class TestParserRegistryInsert:
    def test_insert_at_beginning(self) -> None:
        """Req 10.4: insert at any position without modifying existing parsers."""
        original = AlwaysMatchParser(parameter_type=ParameterType.json)
        reg = ParserRegistry(parsers=[original])

        new_parser = AlwaysMatchParser(parameter_type=ParameterType.code)
        reg.insert(0, new_parser)

        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.code

    def test_insert_at_end(self) -> None:
        first = AlwaysMatchParser(parameter_type=ParameterType.json)
        reg = ParserRegistry(parsers=[first])

        appended = AlwaysMatchParser(parameter_type=ParameterType.code)
        reg.insert(1, appended)

        # First parser still wins
        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.json

    def test_insert_preserves_existing_parsers(self) -> None:
        p1 = NeverMatchParser()
        p2 = AlwaysMatchParser(parameter_type=ParameterType.json)
        reg = ParserRegistry(parsers=[p1, p2])

        new = AlwaysMatchParser(parameter_type=ParameterType.code)
        reg.insert(1, new)

        # p1 doesn't match, new matches → code
        result = reg.detect("k", "value")
        assert result.detected_type == ParameterType.code
