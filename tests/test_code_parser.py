"""Unit tests for CodeParser."""

from __future__ import annotations

import pytest

from trajectory_eval.models.tool import ParameterType, SubParameter, ToolParameter
from trajectory_eval.parsers.parameter.code import CodeParser


@pytest.fixture
def parser() -> CodeParser:
    return CodeParser()


# --- can_parse tests ---


class TestCodeParserCanParse:
    """Tests for CodeParser.can_parse (Req 7.1, 7.3, 12.2)."""

    def test_valid_python_with_def(self, parser: CodeParser) -> None:
        code = "def hello():\n    return 42\n"
        assert parser.can_parse(code) is True

    def test_valid_python_with_class(self, parser: CodeParser) -> None:
        code = "class Foo:\n    pass\n"
        assert parser.can_parse(code) is True

    def test_valid_python_with_import(self, parser: CodeParser) -> None:
        code = "import os\nimport sys\n"
        assert parser.can_parse(code) is True

    def test_valid_python_with_from_import(self, parser: CodeParser) -> None:
        code = "from os.path import join\n"
        assert parser.can_parse(code) is True

    def test_valid_python_with_async_def(self, parser: CodeParser) -> None:
        code = "async def fetch():\n    return None\n"
        assert parser.can_parse(code) is True

    def test_valid_python_with_decorator(self, parser: CodeParser) -> None:
        code = "@staticmethod\ndef foo():\n    pass\n"
        assert parser.can_parse(code) is True

    def test_valid_python_with_return(self, parser: CodeParser) -> None:
        code = "def f(x):\n    return x + 1\n"
        assert parser.can_parse(code) is True

    def test_valid_python_with_yield(self, parser: CodeParser) -> None:
        code = "def gen():\n    yield 1\n    yield 2\n"
        assert parser.can_parse(code) is True

    def test_plain_text_without_keywords(self, parser: CodeParser) -> None:
        assert parser.can_parse("hello world") is False

    def test_keywords_but_invalid_syntax(self, parser: CodeParser) -> None:
        # Has keyword but isn't valid Python
        assert parser.can_parse("def (broken syntax!!!") is False

    def test_non_string_value(self, parser: CodeParser) -> None:
        assert parser.can_parse(42) is False
        assert parser.can_parse(None) is False
        assert parser.can_parse(["def foo(): pass"]) is False

    def test_empty_string(self, parser: CodeParser) -> None:
        assert parser.can_parse("") is False

    def test_if_name_main(self, parser: CodeParser) -> None:
        code = 'if __name__ == "__main__":\n    print("hi")\n'
        assert parser.can_parse(code) is True


# --- parse tests ---


class TestCodeParserParse:
    """Tests for CodeParser.parse (Req 7.2)."""

    def test_returns_tool_parameter_with_code_type(self, parser: CodeParser) -> None:
        code = "def hello():\n    return 42\n"
        result = parser.parse("file_text", code)

        assert isinstance(result, ToolParameter)
        assert result.key == "file_text"
        assert result.raw_value == code
        assert result.detected_type == ParameterType.code

    def test_single_sub_parameter_code_body(self, parser: CodeParser) -> None:
        code = "import os\n\ndef main():\n    pass\n"
        result = parser.parse("content", code)

        assert len(result.sub_parameters) == 1
        sub = result.sub_parameters[0]
        assert sub.name == "code_body"
        assert sub.value == code
        assert sub.detected_type == ParameterType.code

    def test_preserves_raw_value(self, parser: CodeParser) -> None:
        code = "class Foo:\n    x = 1\n"
        result = parser.parse("source", code)
        assert result.raw_value == code

    def test_parameter_type_attribute(self, parser: CodeParser) -> None:
        assert parser.parameter_type == ParameterType.code
