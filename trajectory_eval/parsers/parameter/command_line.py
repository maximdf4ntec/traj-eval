"""CommandLineParser — detects and decomposes shell command strings.

Splits a shell command string into typed subcomponents: command name,
flags, option-value pairs, positional arguments, file paths, and
redirection targets.  Handles pipe boundaries and preserves quoted
arguments as single tokens.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from trajectory_eval.models.tool import ParameterType, SubParameter, ToolParameter
from trajectory_eval.parsers.parameter.base import ParameterParser

# Common shell tool names used for detection heuristic.
_COMMON_TOOLS: frozenset[str] = frozenset(
    [
        "grep",
        "find",
        "ls",
        "cat",
        "cd",
        "cp",
        "mv",
        "rm",
        "mkdir",
        "rmdir",
        "touch",
        "chmod",
        "chown",
        "echo",
        "sed",
        "awk",
        "sort",
        "head",
        "tail",
        "wc",
        "curl",
        "wget",
        "tar",
        "zip",
        "unzip",
        "git",
        "python",
        "python3",
        "pip",
        "pip3",
        "pytest",
        "node",
        "npm",
        "npx",
        "yarn",
        "docker",
        "kubectl",
        "make",
        "cargo",
        "rustc",
        "go",
        "java",
        "javac",
        "gcc",
        "g++",
        "clang",
        "bash",
        "sh",
        "zsh",
        "ssh",
        "scp",
        "rsync",
        "diff",
        "patch",
        "xargs",
        "tee",
        "kill",
        "ps",
        "top",
        "df",
        "du",
        "ln",
        "export",
        "source",
        "which",
        "env",
        "sudo",
        "apt",
        "apt-get",
        "yum",
        "brew",
        "man",
    ]
)

# Regex for detecting flags anywhere in the string.
_RE_FLAG = re.compile(r"(?:^|\s)--?\w")

# Pattern for file paths (Unix-style or Windows-style) within tokens.
_RE_UNIX_PATH = re.compile(r"^[./~]?/[a-zA-Z0-9_./-]+$")
_RE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:\\")

# Pattern to detect if a string looks like JSON or code (to reject them).
_RE_JSON_START = re.compile(r"^\s*[\[{]")
_RE_CODE_KEYWORDS = re.compile(
    r"(?:^|\n)\s*(?:def |class |import |from |if __name__|return |yield )"
)


def _looks_like_command(value: str) -> bool:
    """Return True if *value* looks like a shell command string.

    Heuristics:
    - Must not be empty or just whitespace.
    - Must not look like JSON (starts with { or [).
    - Must not look like Python code (contains Python keywords at line start).
    - At least one of: leading word is a common tool, flags present,
      contains pipe |, or has typical command structure (word + space + args).
    """
    stripped = value.strip()
    if not stripped:
        return False

    # Reject JSON-like strings.
    if _RE_JSON_START.match(stripped):
        return False

    # Reject multi-line Python code (code parser should handle these).
    if _RE_CODE_KEYWORDS.search(stripped):
        return False

    # Extract the first word (the potential command name).
    first_word = stripped.split()[0] if stripped.split() else ""

    # Remove leading path to get base command name (e.g., /usr/bin/grep → grep).
    base_name = first_word.rsplit("/", 1)[-1] if "/" in first_word else first_word
    # Handle Windows paths in command names.
    base_name = base_name.rsplit("\\", 1)[-1] if "\\" in base_name else base_name

    # Check if it's a known tool.
    if base_name.lower() in _COMMON_TOOLS:
        return True

    # Check for flags (--something or -x).
    if _RE_FLAG.search(stripped):
        return True

    # Check for pipe operator (strong command-line signal).
    if "|" in stripped:
        return True

    # Check for redirection operators.
    if ">>" in stripped or re.search(r"(?<!\w)>(?!\w*=)", stripped):
        return True

    # Basic command pattern: a word followed by space and more content,
    # where the first word doesn't contain special chars that suggest
    # it's something else (like a URL or code).
    if " " in stripped and first_word.isidentifier():
        return True

    return False


def _is_file_path_token(token: str) -> bool:
    """Return True if *token* looks like a file path."""
    if _RE_UNIX_PATH.match(token):
        return True
    if _RE_WINDOWS_PATH.match(token):
        return True
    # Relative paths with directory separators and extensions.
    if "/" in token and "." in token.rsplit("/", 1)[-1]:
        return True
    return False


def _is_flag(token: str) -> bool:
    """Return True if *token* is a command-line flag."""
    return token.startswith("-") and not token == "-"


def _parse_segment(tokens: list[str]) -> list[SubParameter]:
    """Parse a single command segment (between pipes) into SubParameters.

    Args:
        tokens: The shlex-split tokens for one pipe segment.

    Returns:
        A list of SubParameter instances for this segment.
    """
    if not tokens:
        return []

    sub_params: list[SubParameter] = []
    i = 0

    # First token is the command name.
    sub_params.append(
        SubParameter(
            name="command_name",
            value=tokens[0],
            detected_type=ParameterType.command_line,
        )
    )
    i = 1

    while i < len(tokens):
        token = tokens[i]

        # Handle redirection operators.
        if token in (">", ">>"):
            if i + 1 < len(tokens):
                sub_params.append(
                    SubParameter(
                        name="redirection_target",
                        value=tokens[i + 1],
                        detected_type=ParameterType.file_path,
                    )
                )
                i += 2
            else:
                # Dangling redirection with no target — treat as positional.
                sub_params.append(
                    SubParameter(
                        name="positional_arg",
                        value=token,
                        detected_type=ParameterType.plain_text,
                    )
                )
                i += 1
            continue

        # Handle flags and option-value pairs.
        if _is_flag(token):
            # Check if this is an option-value pair (flag followed by a non-flag value).
            if (
                i + 1 < len(tokens)
                and not _is_flag(tokens[i + 1])
                and tokens[i + 1] not in ("|", ">", ">>")
            ):
                # Option-value pair: use the flag name (stripped of leading dashes) as the name.
                option_key = token.lstrip("-")
                option_value = tokens[i + 1]
                detected = ParameterType.plain_text
                if _is_file_path_token(option_value):
                    detected = ParameterType.file_path
                sub_params.append(
                    SubParameter(
                        name=option_key,
                        value=option_value,
                        detected_type=detected,
                    )
                )
                i += 2
            else:
                # Standalone flag (boolean flag).
                sub_params.append(
                    SubParameter(
                        name="flag",
                        value=token,
                        detected_type=ParameterType.plain_text,
                    )
                )
                i += 1
            continue

        # Handle file paths.
        if _is_file_path_token(token):
            sub_params.append(
                SubParameter(
                    name="file_path",
                    value=token,
                    detected_type=ParameterType.file_path,
                )
            )
            i += 1
            continue

        # Everything else is a positional argument.
        sub_params.append(
            SubParameter(
                name="positional_arg",
                value=token,
                detected_type=ParameterType.plain_text,
            )
        )
        i += 1

    return sub_params


def _shlex_split_safe(segment: str) -> list[str]:
    """Split a command segment using shlex, falling back on whitespace split.

    Uses posix=True to handle quoting properly. Falls back to simple
    whitespace split if shlex raises (e.g., unmatched quotes).
    """
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        # Fallback: split on whitespace but try to preserve obvious quoting.
        return segment.split()


class CommandLineParser(ParameterParser):
    """Detects and decomposes shell command strings.

    Detection uses heuristics: known tool names, presence of flags,
    pipe operators, redirection operators, or a leading identifier
    followed by arguments.

    Decomposition splits on pipe ``|`` boundaries, then within each
    segment extracts command name, flags, option-value pairs, file paths,
    redirection targets, and positional arguments.  Quoted content
    (single or double quotes) is preserved as single unsplit tokens
    via ``shlex.split``.
    """

    parameter_type: ParameterType = ParameterType.command_line

    def can_parse(self, value: Any) -> bool:
        """Return True when *value* looks like a shell command string.

        Validates:
            - Requirement 6.1: Shell command pattern detection
        """
        if not isinstance(value, str):
            return False
        return _looks_like_command(value)

    def parse(self, key: str, value: Any) -> ToolParameter:
        """Decompose a shell command string into typed SubParameters.

        Handles pipe ``|`` as command boundaries, ``>``/``>>`` as
        redirection, flags, option-value pairs, file paths, and
        preserves quoted arguments as single tokens.

        Validates:
            - Requirement 6.2: command_name extraction
            - Requirement 6.3: flag extraction
            - Requirement 6.4: option-value pairs
            - Requirement 6.5: file_path positional args
            - Requirement 6.6: pipe as command boundary
            - Requirement 6.7: redirection_target extraction
            - Requirement 6.8: quoted argument preservation
        """
        text = value if isinstance(value, str) else str(value)

        # Split on pipe boundaries.
        # We split the raw string on ' | ' (with spaces) to avoid splitting
        # on | inside filenames. Also handle bare | at word boundaries.
        segments = re.split(r"\s*\|\s*", text.strip())

        all_sub_params: list[SubParameter] = []

        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue

            # Handle redirection within the segment before shlex splitting.
            # We need to ensure > and >> are separate tokens for parsing.
            # Insert spaces around redirection operators so shlex sees them as tokens.
            segment = re.sub(r"(>>)", r" \1 ", segment)
            segment = re.sub(r"(?<!>)(>)(?!>)", r" \1 ", segment)

            tokens = _shlex_split_safe(segment)
            sub_params = _parse_segment(tokens)
            all_sub_params.extend(sub_params)

        return ToolParameter(
            key=key,
            raw_value=value,
            detected_type=ParameterType.command_line,
            sub_parameters=all_sub_params,
        )
