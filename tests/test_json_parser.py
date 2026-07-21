"""Unit tests for JsonParser."""

from __future__ import annotations

import json

import pytest

from trajectory_eval.models.tool import ParameterType, SubParameter, ToolParameter
from trajectory_eval.parsers.parameter.json_parser import JsonParser


@pytest.fixture
def parser() -> JsonParser:
    return JsonParser()


# --- can_parse tests ---


class TestCanParse:
    """Tests for JsonParser.can_parse — Requirement 9.1, 12.1."""

    def test_valid_json_object(self, parser: JsonParser) -> None:
        assert parser.can_parse('{"key": "value"}') is True

    def test_valid_json_array(self, parser: JsonParser) -> None:
        assert parser.can_parse("[1, 2, 3]") is True

    def test_empty_json_object(self, parser: JsonParser) -> None:
        assert parser.can_parse("{}") is True

    def test_empty_json_array(self, parser: JsonParser) -> None:
        assert parser.can_parse("[]") is True

    def test_json_with_leading_whitespace(self, parser: JsonParser) -> None:
        assert parser.can_parse('  {"a": 1}') is True

    def test_json_with_trailing_whitespace(self, parser: JsonParser) -> None:
        assert parser.can_parse('{"a": 1}  ') is True

    def test_plain_text_returns_false(self, parser: JsonParser) -> None:
        assert parser.can_parse("hello world") is False

    def test_number_string_returns_false(self, parser: JsonParser) -> None:
        assert parser.can_parse("42") is False

    def test_non_string_returns_false(self, parser: JsonParser) -> None:
        assert parser.can_parse(42) is False
        assert parser.can_parse(None) is False
        assert parser.can_parse(["a", "b"]) is False

    def test_invalid_json_starting_with_brace(self, parser: JsonParser) -> None:
        assert parser.can_parse("{not json at all}") is False

    def test_nested_json_object(self, parser: JsonParser) -> None:
        assert parser.can_parse('{"outer": {"inner": 1}}') is True

    def test_json_string_literal_not_object_or_array(self, parser: JsonParser) -> None:
        # A JSON string like '"hello"' is valid JSON but not object/array
        assert parser.can_parse('"hello"') is False


# --- parse tests for JSON objects ---


class TestParseObject:
    """Tests for JsonParser.parse on JSON objects — Requirement 9.2."""

    def test_simple_object_keys(self, parser: JsonParser) -> None:
        value = '{"name": "Alice", "age": 30}'
        result = parser.parse("data", value)

        assert result.key == "data"
        assert result.raw_value == value
        assert result.detected_type == ParameterType.json
        assert len(result.sub_parameters) == 2

    def test_sub_parameter_names_match_keys(self, parser: JsonParser) -> None:
        value = '{"foo": 1, "bar": 2}'
        result = parser.parse("param", value)

        names = [sp.name for sp in result.sub_parameters]
        assert "foo" in names
        assert "bar" in names

    def test_sub_parameter_values(self, parser: JsonParser) -> None:
        value = '{"x": "hello", "y": 42}'
        result = parser.parse("param", value)

        by_name = {sp.name: sp.value for sp in result.sub_parameters}
        assert by_name["x"] == "hello"
        assert by_name["y"] == 42

    def test_sub_parameters_have_plain_text_type(self, parser: JsonParser) -> None:
        value = '{"key": [1, 2, 3]}'
        result = parser.parse("param", value)

        for sp in result.sub_parameters:
            assert sp.detected_type == ParameterType.plain_text

    def test_sub_parameters_have_empty_sub_parameters(self, parser: JsonParser) -> None:
        value = '{"key": {"nested": true}}'
        result = parser.parse("param", value)

        for sp in result.sub_parameters:
            assert sp.sub_parameters == []

    def test_empty_object_produces_no_sub_parameters(self, parser: JsonParser) -> None:
        result = parser.parse("param", "{}")
        assert result.detected_type == ParameterType.json
        assert result.sub_parameters == []

    def test_key_count_matches_top_level_keys(self, parser: JsonParser) -> None:
        """Property 8: number of SubParameters equals number of top-level keys."""
        obj = {"a": 1, "b": "two", "c": [3], "d": None, "e": True}
        value = json.dumps(obj)
        result = parser.parse("param", value)
        assert len(result.sub_parameters) == len(obj)


# --- parse tests for JSON arrays ---


class TestParseArray:
    """Tests for JsonParser.parse on JSON arrays — Requirement 9.3."""

    def test_array_element_names(self, parser: JsonParser) -> None:
        value = '["a", "b", "c"]'
        result = parser.parse("items", value)

        assert result.detected_type == ParameterType.json
        names = [sp.name for sp in result.sub_parameters]
        assert names == ["element_0", "element_1", "element_2"]

    def test_array_element_values(self, parser: JsonParser) -> None:
        value = "[10, 20, 30]"
        result = parser.parse("nums", value)

        values = [sp.value for sp in result.sub_parameters]
        assert values == [10, 20, 30]

    def test_array_sub_parameters_have_plain_text_type(
        self, parser: JsonParser
    ) -> None:
        value = '[{"nested": true}]'
        result = parser.parse("items", value)

        for sp in result.sub_parameters:
            assert sp.detected_type == ParameterType.plain_text
            assert sp.sub_parameters == []

    def test_empty_array_produces_no_sub_parameters(self, parser: JsonParser) -> None:
        result = parser.parse("items", "[]")
        assert result.detected_type == ParameterType.json
        assert result.sub_parameters == []

    def test_array_count_matches_elements(self, parser: JsonParser) -> None:
        value = json.dumps([1, 2, 3, 4, 5])
        result = parser.parse("items", value)
        assert len(result.sub_parameters) == 5
