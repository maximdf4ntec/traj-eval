"""Execution Report — secondary output artifact from the contract compiler.

This module defines the Execution Report data model, which captures behavioral
observations (metrics) and unresolvable inconsistency flags that are excluded
from the deterministic Behavior Contract.

The report complements the Behavior Contract: while the contract contains only
deterministic, step-agnostic invariants suitable for regression testing, the
Execution Report contains efficiency metrics, optimization observations, and
patterns that were too inconsistent to become contract rules.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from trajectory_eval.models.contract import GeneratorInfo, RuleCategory


class MetricObservation(BaseModel):
    """A single metrics-rule observation.

    Attributes:
        rule_class: The name of the metrics rule class that produced this
            observation (e.g. ``"RedundancyRateRule"``).
        category: A human-readable category for the metric
            (e.g. ``"efficiency"``).
        observation: Rule-specific payload containing the computed metric
            values. Structure varies by rule class.
    """

    rule_class: str
    category: str
    observation: dict[str, Any]


class InconsistencyFlag(BaseModel):
    """A contradictory pattern that could not be resolved into a contract rule.

    When multiple observations from the same rule class produce conflicting
    constraints for the same target, the deduplicator emits a flag instead
    of a contract rule.

    Attributes:
        target_fingerprint: Canonical identity key for the conflicting
            target (e.g. ``"interface::param_type::{"tool":"foo","parameter":"bar"}"``)
        category: The rule category of the conflicting observations.
        kind: The rule kind of the conflicting observations.
        conflicting_constraints: The differing constraint dicts that could
            not be merged.
        observation_count: How many observations were in the conflicting
            group.
    """

    target_fingerprint: str
    category: RuleCategory
    kind: str
    conflicting_constraints: list[dict[str, Any]]
    observation_count: int


class ExecutionReport(BaseModel):
    """Secondary output artifact — metrics + flags.

    Produced alongside the Behavior Contract by the ContractCompiler.
    Contains behavioral observations from metrics-only rules and
    inconsistency flags from the deduplication process.

    Attributes:
        schema_version: Schema version for the execution report format.
        generator: Identifies the compiler version that produced this report.
        metrics: Observations from all metrics-only rules
            (RedundancyRateRule, TokenEfficiencyRule, MonotonicProgressRule,
            CycleBreakRule).
        flags: All inconsistent patterns that could not be resolved into
            deterministic contract rules.
    """

    schema_version: Literal[1] = 1
    generator: GeneratorInfo = Field(default_factory=GeneratorInfo)
    metrics: list[MetricObservation]
    flags: list[InconsistencyFlag]
