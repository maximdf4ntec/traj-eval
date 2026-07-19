"""Concrete HardRule subclasses — one class per rule variant.

Exports
-------
Trajectory-level rules (a–g):
    RedundancyRateRule      — Rule a
    MonotonicProgressRule   — Rule b
    ToolSequenceRule        — Rule c (positive + negative instances)
    DataDependencyRule      — Rule d
    CycleBreakRule          — Rule e
    TokenEfficiencyRule     — Rule f
    MutationMatcherRule     — Rule g

Per-step rules (h):
    ToolParamCountRule      — Rule h (count)
    ToolParamTypeRule       — Rule h (type)
"""

from trajectory_eval.generator.rules.redundancy_rate import RedundancyRateRule
from trajectory_eval.generator.rules.monotonic_progress import MonotonicProgressRule
from trajectory_eval.generator.rules.tool_sequence import ToolSequenceRule
from trajectory_eval.generator.rules.data_dependency import DataDependencyRule
from trajectory_eval.generator.rules.cycle_breaker import CycleBreakRule
from trajectory_eval.generator.rules.token_efficiency import TokenEfficiencyRule
from trajectory_eval.generator.rules.mutation_matcher import MutationMatcherRule
from trajectory_eval.generator.rules.tool_checks import (
    ToolParamCountRule,
    ToolParamTypeRule,
)
from trajectory_eval.generator.rules.terminal_state import TerminalStateRule
from trajectory_eval.generator.rules.tool_result_type import ToolResultTypeRule
from trajectory_eval.generator.rules.llm_format import LlmResponseFormatRule
from trajectory_eval.generator.rules.llm_grounding import LlmGroundingRule

__all__ = [
    "RedundancyRateRule",
    "MonotonicProgressRule",
    "ToolSequenceRule",
    "DataDependencyRule",
    "CycleBreakRule",
    "TokenEfficiencyRule",
    "MutationMatcherRule",
    "ToolParamCountRule",
    "ToolParamTypeRule",
    "TerminalStateRule",
    "ToolResultTypeRule",
    "LlmResponseFormatRule",
    "LlmGroundingRule",
]
