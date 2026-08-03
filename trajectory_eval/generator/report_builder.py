"""Report Builder — assembles the Execution Report from metrics and flags.

The ReportBuilder converts internal metrics rule instances (RedundancyRateRule,
TokenEfficiencyRule, MonotonicProgressRule, CycleBreakRule) into
MetricObservation entries and combines them with inconsistency flags produced
by the RuleDeduplicator into a complete ExecutionReport.
"""

from __future__ import annotations

from typing import Any

from trajectory_eval.generator.rules.cycle_breaker import CycleBreakRule
from trajectory_eval.generator.rules.latency_budget import LatencyBudgetRule
from trajectory_eval.generator.rules.monotonic_progress import MonotonicProgressRule
from trajectory_eval.generator.rules.redundancy_rate import RedundancyRateRule
from trajectory_eval.generator.rules.token_budget import TokenBudgetRule
from trajectory_eval.generator.rules.token_efficiency import TokenEfficiencyRule
from trajectory_eval.models.execution_report import (
    ExecutionReport,
    InconsistencyFlag,
    MetricObservation,
)
from trajectory_eval.models.rule import HardRule


# Classification: rule class → human-readable category for the report.
_CATEGORY_MAP: dict[type, str] = {
    RedundancyRateRule: "efficiency",
    TokenEfficiencyRule: "efficiency",
    MonotonicProgressRule: "progress",
    CycleBreakRule: "efficiency",
    TokenBudgetRule: "performance",
    LatencyBudgetRule: "performance",
}


def _extract_observation(rule: HardRule) -> dict[str, Any]:
    """Extract rule-specific computed values into a plain dict.

    Each metrics rule class has distinct fields that represent its computed
    observation. This function pulls out only the rule-specific payload,
    excluding base-class metadata fields.
    """
    if isinstance(rule, RedundancyRateRule):
        return {
            "max_rate": rule.max_rate,
            "observed_rate": rule.observed_rate,
            "duplicate_count": rule.duplicate_count,
            "total_count": rule.total_count,
        }
    if isinstance(rule, TokenEfficiencyRule):
        return {
            "prev_step": rule.prev_step,
            "prev_token_count": rule.prev_token_count,
            "curr_token_count": rule.curr_token_count,
            "max_growth_ratio": rule.max_growth_ratio,
            "observed_ratio": rule.observed_ratio,
        }
    if isinstance(rule, MonotonicProgressRule):
        return {
            "step_index_compared": rule.step_index_compared,
            "stagnation_threshold": rule.stagnation_threshold,
            "observed_similarity": rule.observed_similarity,
        }
    if isinstance(rule, CycleBreakRule):
        return {
            "prior_step": rule.prior_step,
            "repeated_tool_name": rule.repeated_tool_name,
            "horizon": rule.horizon,
            "repetition_count": rule.repetition_count,
        }
    if isinstance(rule, TokenBudgetRule):
        return {
            "step_index": rule.step_index,
            "step_type": rule.step_type.value if rule.step_type else None,
            "observed_tokens": rule.observed_tokens,
            "threshold_tokens": rule.threshold_tokens,
            "token_budget_pct": rule.token_budget_pct,
        }
    if isinstance(rule, LatencyBudgetRule):
        return {
            "step_index": rule.step_index,
            "step_type": rule.step_type.value if rule.step_type else None,
            "observed_latency_ms": rule.observed_latency_ms,
            "threshold_latency_ms": rule.threshold_latency_ms,
            "latency_budget_pct": rule.latency_budget_pct,
        }
    # Fallback: dump all non-base fields via model_dump, excluding inherited
    # Rule fields so we get only the rule-specific payload.
    base_fields = {
        "id",
        "step_index",
        "polarity",
        "scope",
        "step_type",
        "confidence",
        "rule_description",
        "rule_type",
        "pseudocode",
    }
    return {k: v for k, v in rule.model_dump().items() if k not in base_fields}


class ReportBuilder:
    """Assembles the Execution Report from metrics and flags."""

    def build(
        self,
        metrics_rules: list[HardRule],
        flags: list[InconsistencyFlag],
    ) -> ExecutionReport:
        """Build an ExecutionReport from metrics rule instances and flags.

        Args:
            metrics_rules: HardRule instances from metrics-only rule classes
                (RedundancyRateRule, TokenEfficiencyRule, MonotonicProgressRule,
                CycleBreakRule).
            flags: Inconsistency flags produced by the RuleDeduplicator when
                contradictory patterns are detected.

        Returns:
            A fully populated ExecutionReport with schema_version, generator,
            metrics observations, and inconsistency flags.
        """
        metrics: list[MetricObservation] = []

        for rule in metrics_rules:
            rule_class_name = type(rule).__name__
            category = _CATEGORY_MAP.get(type(rule), "unknown")
            observation = _extract_observation(rule)

            metrics.append(
                MetricObservation(
                    rule_class=rule_class_name,
                    category=category,
                    observation=observation,
                )
            )

        return ExecutionReport(
            metrics=metrics,
            flags=flags,
        )
