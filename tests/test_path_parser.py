"""Unit and property-based tests for PathParser."""

from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trajectory_eval.models.tool import ParameterType, ToolParameter
from trajectory_eval.parsers.parameter.path import PathParser, _is_file_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def parser() -> PathParser:
    return PathParser()


# ---------------------------------------------------------------------------
# Unit tests — can_parse
# ---------------------------------------------------------------------------


class TestPathParserCanParse:
    """Unit tests for PathParser.can_parse (Reqs 8.1, 8.2, 12.3)."""

    def test_unix_simple_path(self, parser: PathParser) -> None:
        assert parser.can_parse("/usr/bin/python3.exe") is True

    def test_unix_nested_path(self, parser: PathParser) -> None:
        assert parser.can_parse("/home/user/project/src/main.py") is True

    def test_unix_path_with_dots_in_dir(self, parser: PathParser) -> None:
        assert parser.can_parse("/testbed/boltons/tableutils.py") is True

    def test_unix_path_with_underscores(self, parser: PathParser) -> None:
        assert parser.can_parse("/var/log/app_server.log") is True

    def test_unix_path_short_extension(self, parser: PathParser) -> None:
        assert parser.can_parse("/a/b.c") is True

    def test_windows_path_simple(self, parser: PathParser) -> None:
        assert parser.can_parse(r"C:\Users\admin\file.txt") is True

    def test_windows_path_nested(self, parser: PathParser) -> None:
        assert parser.can_parse(r"D:\Projects\src\main.py") is True

    def test_windows_path_lowercase_drive(self, parser: PathParser) -> None:
        assert parser.can_parse(r"c:\work\project\test.js") is True

    def test_rejects_relative_path(self, parser: PathParser) -> None:
        assert parser.can_parse("src/main.py") is False

    def test_rejects_plain_text(self, parser: PathParser) -> None:
        assert parser.can_parse("hello world") is False

    def test_rejects_empty_string(self, parser: PathParser) -> None:
        assert parser.can_parse("") is False

    def test_rejects_non_string(self, parser: PathParser) -> None:
        assert parser.can_parse(42) is False
        assert parser.can_parse(None) is False
        assert parser.can_parse(["path"]) is False

    def test_rejects_unix_no_extension(self, parser: PathParser) -> None:
        # _is_file_path_output requires an extension
        assert parser.can_parse("/usr/bin/python") is False

    def test_rejects_multiline(self, parser: PathParser) -> None:
        # PathParser handles single paths only
        assert parser.can_parse("/foo/bar.py\n/baz/qux.py") is False

    def test_rejects_path_with_spaces_in_name(self, parser: PathParser) -> None:
        # The regex doesn't allow spaces in paths
        assert parser.can_parse("/foo/bar baz.py") is False


# ---------------------------------------------------------------------------
# Unit tests — parse
# ---------------------------------------------------------------------------


class TestPathParserParse:
    """Unit tests for PathParser.parse (Req 8.3)."""

    def test_parse_returns_tool_parameter(self, parser: PathParser) -> None:
        result = parser.parse("file", "/home/user/test.py")
        assert isinstance(result, ToolParameter)

    def test_parse_detected_type_is_file_path(self, parser: PathParser) -> None:
        result = parser.parse("path", "/testbed/main.py")
        assert result.detected_type == ParameterType.file_path

    def test_parse_sub_parameters_empty(self, parser: PathParser) -> None:
        result = parser.parse("path", "/testbed/main.py")
        assert result.sub_parameters == []

    def test_parse_preserves_key(self, parser: PathParser) -> None:
        result = parser.parse("file_path", "/a/b.txt")
        assert result.key == "file_path"

    def test_parse_preserves_raw_value(self, parser: PathParser) -> None:
        val = "/home/user/docs/report.pdf"
        result = parser.parse("doc", val)
        assert result.raw_value == val

    def test_parse_windows_path(self, parser: PathParser) -> None:
        val = r"C:\Users\admin\file.txt"
        result = parser.parse("path", val)
        assert result.detected_type == ParameterType.file_path
        assert result.raw_value == val
        assert result.sub_parameters == []


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


# Strategy: generate valid Unix paths
_unix_path_st = st.from_regex(
    r"/[a-zA-Z0-9_][a-zA-Z0-9_./\-]{0,50}\.[a-zA-Z]{1,10}", fullmatch=True
).filter(lambda p: "//" not in p and not p.endswith("/"))

# Strategy: generate valid Windows paths
_windows_path_st = st.from_regex(
    r"[A-Za-z]:\\[a-zA-Z0-9_\\]{1,50}\.[a-zA-Z]{1,10}", fullmatch=True
)


class TestPathParserProperties:
    """Property-based tests for PathParser.

    **Validates: Requirements 8.1, 8.2, 8.3, 12.3**
    """

    @given(path=_unix_path_st)
    @settings(max_examples=200)
    def test_unix_paths_detected(self, path: str) -> None:
        """Any well-formed Unix absolute path with extension is detected.

        **Validates: Requirements 8.1**
        """
        parser = PathParser()
        assert parser.can_parse(path) is True

    @given(path=_windows_path_st)
    @settings(max_examples=200)
    def test_windows_paths_detected(self, path: str) -> None:
        """Any well-formed Windows absolute path is detected.

        **Validates: Requirements 8.2**
        """
        parser = PathParser()
        assert parser.can_parse(path) is True

    @given(path=_unix_path_st)
    @settings(max_examples=100)
    def test_parse_produces_file_path_type_with_empty_sub_params(
        self, path: str
    ) -> None:
        """Parsed paths always have detected_type=file_path and empty sub_parameters.

        **Validates: Requirements 8.3**
        """
        parser = PathParser()
        result = parser.parse("file", path)
        assert result.detected_type == ParameterType.file_path
        assert result.sub_parameters == []
        assert result.raw_value == path
        assert result.key == "file"

    @given(
        path=st.sampled_from(
            [
                "/testbed/boltons/tableutils.py",
                "/home/user/project/src/main.py",
                "/var/log/app.log",
                "/a/b.c",
                "/usr/local/bin/tool.sh",
                "/tmp/output.txt",
                "/root/.config/settings.json",
            ]
        )
    )
    @settings(max_examples=50)
    def test_parity_with_is_file_path_output(self, path: str) -> None:
        """PathParser.can_parse is consistent with _is_file_path_output for single paths.

        **Validates: Requirements 12.3**
        """
        from trajectory_eval.generator.rules.tool_result_type import (
            _is_file_path_output,
        )

        parser = PathParser()
        # If the output detector says it's a file path, so should PathParser
        if _is_file_path_output(path):
            assert parser.can_parse(path) is True
