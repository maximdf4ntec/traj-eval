"""Unit tests for CommandLineParser."""

from __future__ import annotations

import pytest

from trajectory_eval.models.tool import ParameterType, SubParameter
from trajectory_eval.parsers.parameter.command_line import CommandLineParser


@pytest.fixture
def parser() -> CommandLineParser:
    return CommandLineParser()


# --- can_parse detection tests ---


class TestCanParse:
    """Tests for command-line detection heuristic (Req 6.1)."""

    def test_common_tool_name(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("grep -r pattern .") is True

    def test_git_command(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("git commit -m 'fix bug'") is True

    def test_python_invocation(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("python -m pytest tests/") is True

    def test_flags_detected(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("myapp --verbose --output file.txt") is True

    def test_pipe_detected(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("cat file.txt | grep error") is True

    def test_redirection_detected(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("echo hello > output.txt") is True

    def test_simple_identifier_with_args(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("run something here") is True

    def test_rejects_json(self, parser: CommandLineParser) -> None:
        assert parser.can_parse('{"key": "value"}') is False

    def test_rejects_json_array(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("[1, 2, 3]") is False

    def test_rejects_python_code(self, parser: CommandLineParser) -> None:
        code = "def hello():\n    return 'world'"
        assert parser.can_parse(code) is False

    def test_rejects_empty_string(self, parser: CommandLineParser) -> None:
        assert parser.can_parse("") is False

    def test_rejects_non_string(self, parser: CommandLineParser) -> None:
        assert parser.can_parse(42) is False
        assert parser.can_parse(None) is False
        assert parser.can_parse(["ls"]) is False


# --- parse: command_name extraction (Req 6.2) ---


class TestCommandNameExtraction:
    """Tests for command_name SubParameter extraction."""

    def test_simple_command(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "ls -la")
        names = [sp for sp in result.sub_parameters if sp.name == "command_name"]
        assert len(names) == 1
        assert names[0].value == "ls"

    def test_path_command(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "grep pattern file.txt")
        names = [sp for sp in result.sub_parameters if sp.name == "command_name"]
        assert len(names) == 1
        assert names[0].value == "grep"


# --- parse: flag extraction (Req 6.3) ---


class TestFlagExtraction:
    """Tests for flag SubParameter extraction."""

    def test_short_flag(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "ls -l")
        flags = [sp for sp in result.sub_parameters if sp.name == "flag"]
        assert any(f.value == "-l" for f in flags)

    def test_long_flag(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "pytest --verbose")
        flags = [sp for sp in result.sub_parameters if sp.name == "flag"]
        assert any(f.value == "--verbose" for f in flags)

    def test_multiple_flags(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "ls -la --all --color")
        flags = [sp for sp in result.sub_parameters if sp.name == "flag"]
        # -la is a single flag, --all and --color are standalone flags
        assert len(flags) >= 2


# --- parse: option-value pairs (Req 6.4) ---


class TestOptionValuePairs:
    """Tests for option-value pair SubParameter extraction."""

    def test_long_option_with_value(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "grep --file pattern.txt")
        # --file is treated as option key, pattern.txt as value
        option = [sp for sp in result.sub_parameters if sp.name == "file"]
        assert len(option) == 1
        assert option[0].value == "pattern.txt"

    def test_short_option_with_value(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "head -n 10")
        option = [sp for sp in result.sub_parameters if sp.name == "n"]
        assert len(option) == 1
        assert option[0].value == "10"


# --- parse: file_path detection (Req 6.5) ---


class TestFilePathDetection:
    """Tests for file_path SubParameter extraction."""

    def test_unix_path_positional(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "cat /etc/config.yml")
        paths = [sp for sp in result.sub_parameters if sp.name == "file_path"]
        assert any(p.value == "/etc/config.yml" for p in paths)
        assert all(p.detected_type == ParameterType.file_path for p in paths)

    def test_relative_path_with_slash(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "cat src/main.py")
        paths = [sp for sp in result.sub_parameters if sp.name == "file_path"]
        assert any(p.value == "src/main.py" for p in paths)


# --- parse: pipe handling (Req 6.6) ---


class TestPipeHandling:
    """Tests for pipe as command boundary."""

    def test_pipe_splits_commands(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "cat file.txt | grep error")
        names = [sp for sp in result.sub_parameters if sp.name == "command_name"]
        assert len(names) == 2
        assert names[0].value == "cat"
        assert names[1].value == "grep"

    def test_multi_pipe(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "cat file.txt | grep error | wc -l")
        names = [sp for sp in result.sub_parameters if sp.name == "command_name"]
        assert len(names) == 3


# --- parse: redirection (Req 6.7) ---


class TestRedirection:
    """Tests for redirection target extraction."""

    def test_single_redirect(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "echo hello > output.txt")
        targets = [
            sp for sp in result.sub_parameters if sp.name == "redirection_target"
        ]
        assert len(targets) == 1
        assert targets[0].value == "output.txt"

    def test_append_redirect(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "echo hello >> log.txt")
        targets = [
            sp for sp in result.sub_parameters if sp.name == "redirection_target"
        ]
        assert len(targets) == 1
        assert targets[0].value == "log.txt"


# --- parse: quoted argument preservation (Req 6.8) ---


class TestQuotedArguments:
    """Tests for quoted argument preservation."""

    def test_double_quoted_argument(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", 'git commit -m "fix the bug"')
        # "fix the bug" should be preserved as single value
        all_values = [sp.value for sp in result.sub_parameters]
        assert "fix the bug" in all_values

    def test_single_quoted_argument(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "grep 'hello world' file.txt")
        all_values = [sp.value for sp in result.sub_parameters]
        assert "hello world" in all_values

    def test_quoted_path_with_spaces(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "cat '/path/to/my file.txt'")
        all_values = [sp.value for sp in result.sub_parameters]
        assert "/path/to/my file.txt" in all_values


# --- parse: result structure ---


class TestResultStructure:
    """Tests for the overall ToolParameter result structure."""

    def test_detected_type_is_command_line(self, parser: CommandLineParser) -> None:
        result = parser.parse("command", "ls -la")
        assert result.detected_type == ParameterType.command_line

    def test_raw_value_preserved(self, parser: CommandLineParser) -> None:
        cmd = "git push origin main"
        result = parser.parse("command", cmd)
        assert result.raw_value == cmd

    def test_key_preserved(self, parser: CommandLineParser) -> None:
        result = parser.parse("my_key", "ls")
        assert result.key == "my_key"

    def test_always_has_command_name(self, parser: CommandLineParser) -> None:
        """Every parseable command should have at least one command_name."""
        result = parser.parse("command", "ls")
        names = [sp for sp in result.sub_parameters if sp.name == "command_name"]
        assert len(names) >= 1
