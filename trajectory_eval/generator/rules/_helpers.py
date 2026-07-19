"""Shared utility functions used by concrete hard rule classes.

All helpers are pure functions (no side-effects) so they can be called
freely from any ``from_trajectory`` or ``from_step`` classmethod.
"""

from __future__ import annotations

import json
import math
from typing import Optional

from trajectory_eval.models.trajectory import Step, StepType


def is_failed_step(step: Step, failure_keywords: frozenset[str]) -> bool:
    """Return True when a tool_result output contains failure indicators.

    Args:
        step: Any step; non-tool_result steps always return False.
        failure_keywords: Lowercase keyword strings that signal failure.

    Returns:
        True if the output text contains at least one failure keyword.
    """
    if step.step_type != StepType.tool_result:
        return False
    output = (step.tool_output or "").lower()
    return any(kw in output for kw in failure_keywords)


def is_empty_step(step: Step) -> bool:
    """Return True when a tool_result output is blank or a trivial sentinel.

    Args:
        step: Any step; non-tool_result steps always return False.

    Returns:
        True if the output is empty or one of ``null``, ``{}``, ``[]``, ``none``.
    """
    if step.step_type != StepType.tool_result:
        return False
    output = (step.tool_output or "").strip()
    return len(output) == 0 or output in ("null", "{}", "[]", "none")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors (pure Python).

    Args:
        a: First embedding vector.
        b: Second embedding vector.

    Returns:
        Cosine similarity in [-1.0, 1.0]; returns 0.0 for zero vectors.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def preceding_tool_call(steps: list[Step], before_index: int) -> Optional[Step]:
    """Return the most recent tool_call step strictly before *before_index*.

    Args:
        steps: Ordered list of all trajectory steps.
        before_index: Exclusive upper bound on step index.

    Returns:
        The matching Step, or None if not found.
    """
    for s in reversed(steps):
        if s.index < before_index and s.step_type == StepType.tool_call:
            return s
    return None


def next_tool_call(steps: list[Step], after_index: int) -> Optional[Step]:
    """Return the first tool_call step strictly after *after_index*.

    Args:
        steps: Ordered list of all trajectory steps.
        after_index: Exclusive lower bound on step index.

    Returns:
        The matching Step, or None if not found.
    """
    for s in steps:
        if s.index > after_index and s.step_type == StepType.tool_call:
            return s
    return None


def tool_call_signature(step: Step) -> tuple[str, str]:
    """Return a hashable (tool_name, serialised_input) signature for a tool_call step.

    Args:
        step: A tool_call Step.

    Returns:
        A 2-tuple of (tool_name, json_input).
    """
    sig = json.dumps(step.tool_input, sort_keys=True) if step.tool_input else "null"
    return (step.tool_name or "", sig)
