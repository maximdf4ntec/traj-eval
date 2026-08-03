"""
Utilities for extracting normalized facts from tool outputs.

The normalizer converts arbitrary JSON-like tool outputs into a flat list of
atomic facts. Each fact records:

- JSON path
- Original value
- Normalized string representation
- Confidence that the value is useful for provenance tracking

This module is intentionally generic and reusable across multiple rule
generators (lineage, referential integrity, numeric validation, etc.).
"""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any

from pydantic import BaseModel

from trajectory_eval.models.rule import ConfidenceLevel

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    """Single atomic value extracted from a tool output."""

    model_config = {"frozen": True}

    path: str
    value: Any
    value_str: str
    confidence: ConfidenceLevel


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_facts(tool_output: Any) -> list[Fact]:
    """
    Extract all atomic values from a JSON-like object.

    Args:
        tool_output:
            Parsed JSON object (dict/list) or primitive.

    Returns:
        Flat list of extracted facts.
    """
    facts: list[Fact] = []
    _walk(tool_output, "", facts)
    return facts


def normalize_value(value: Any) -> str:
    """
    Normalize a value into a canonical string representation suitable for
    equality comparisons.

    Examples:
        123 -> "123"
        "  ABC  " -> "ABC"
        Path("a/b") -> "a/b"
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, PurePath):
        return value.as_posix()

    return str(value).strip()


def is_candidate_value(value: Any) -> bool:
    """
    Return True if a value is worth tracking for provenance.

    Filters out values that commonly create false positives.
    """

    if value is None:
        return False

    if isinstance(value, bool):
        return False

    if isinstance(value, (dict, list)):
        return False

    if isinstance(value, int):
        return abs(value) > 3

    text = normalize_value(value)

    if not text:
        return False

    if text.lower() in {
        "ok",
        "yes",
        "no",
        "true",
        "false",
        "none",
        "null",
        "success",
        "failure",
    }:
        return False

    return True


def calculate_confidence(value: Any) -> ConfidenceLevel:
    """
    Estimate provenance confidence for a value.

    The confidence reflects how likely a value uniquely identifies an entity
    across a trajectory.
    """

    text = normalize_value(value)

    if _looks_like_uuid(text):
        return ConfidenceLevel.high

    if _looks_like_path(text):
        return ConfidenceLevel.high

    if _looks_like_email(text):
        return ConfidenceLevel.high

    if _looks_like_url(text):
        return ConfidenceLevel.high

    if _looks_like_filename(text):
        return ConfidenceLevel.high

    if isinstance(value, int):
        return ConfidenceLevel.medium

    if len(text) >= 8:
        return ConfidenceLevel.medium

    return ConfidenceLevel.low


# ---------------------------------------------------------------------------
# Recursive traversal
# ---------------------------------------------------------------------------


def _walk(node: Any, path: str, facts: list[Fact]) -> None:
    """Recursively traverse a JSON-like object."""

    if isinstance(node, dict):
        for key, value in node.items():
            next_path = f"{path}.{key}" if path else key
            _walk(value, next_path, facts)
        return

    if isinstance(node, list):
        for i, value in enumerate(node):
            next_path = f"{path}[{i}]"
            _walk(value, next_path, facts)
        return

    if not is_candidate_value(node):
        return

    facts.append(
        Fact(
            path=path,
            value=node,
            value_str=normalize_value(node),
            confidence=calculate_confidence(node),
        )
    )


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-" r"[0-9a-f]{4}-" r"[0-9a-f]{4}-" r"[0-9a-f]{4}-" r"[0-9a-f]{12}$",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_URL_RE = re.compile(r"^https?://")

_FILENAME_RE = re.compile(r"^[^/\\]+\.[A-Za-z0-9]+$")


def _looks_like_uuid(text: str) -> bool:
    return bool(_UUID_RE.fullmatch(text))


def _looks_like_email(text: str) -> bool:
    return bool(_EMAIL_RE.fullmatch(text))


def _looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match(text))


def _looks_like_filename(text: str) -> bool:
    return bool(_FILENAME_RE.fullmatch(text))


def _looks_like_path(text: str) -> bool:
    return "/" in text or "\\" in text


# ---------------------------------------------------------------------------
# Shared value extraction for provenance tracking
# ---------------------------------------------------------------------------

# Canonical file path patterns — the SINGLE source of truth for all rules
# that need to extract file paths from text.
_RE_UNIX_ABSOLUTE_PATH = re.compile(r"/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10}")
_RE_WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:\\[a-zA-Z0-9\\._-]+")
_RE_RELATIVE_PATH = re.compile(
    r"(?<![/\w])[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)+\.[a-zA-Z]{1,10}"
)


def extract_file_paths(text: str) -> list[str]:
    """Extract all file paths (absolute Unix, absolute Windows, relative) from text.

    This is the single canonical file-path extraction used across all rules:
    DataDependencyRule, ToolOutputUtilizationRule, LlmResponseUtilizationRule,
    LlmGroundingRule, and ToolResultTypeRule.

    Args:
        text: Raw text to scan for file paths.

    Returns:
        Deduplicated list of extracted path strings, preserving first-occurrence order.
    """
    seen: set[str] = set()
    paths: list[str] = []

    for pattern in (
        _RE_UNIX_ABSOLUTE_PATH,
        _RE_WINDOWS_ABSOLUTE_PATH,
        _RE_RELATIVE_PATH,
    ):
        for match in pattern.finditer(text):
            val = match.group(0)
            if val not in seen:
                seen.add(val)
                paths.append(val)

    return paths


def extract_trackable_values(text: str) -> list[str]:
    """Extract individual trackable values from a raw text output.

    Splits multi-line text into atomic values suitable for provenance
    matching.  For text containing file paths, extracts each path
    individually.  For short text without paths, returns the text as-is.

    This is the single canonical algorithm used by DataDependencyRule,
    ToolOutputUtilizationRule, and LlmResponseUtilizationRule.

    Args:
        text: Raw text (tool output or parameter value) to decompose.

    Returns:
        List of atomic string values worth tracking.
    """
    normalized = normalize_value(text)
    if not normalized:
        return []

    results: list[str] = extract_file_paths(normalized)

    # If no paths found and value is short enough, use as-is.
    if not results and len(normalized) <= 200:
        results.append(normalized)

    return results
