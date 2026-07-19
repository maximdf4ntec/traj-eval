"""Tests for trajectory_eval.generator.report_builder — ReportBuilder."""

from __future__ import annotations

import pytest

from trajectory_eval.generator.report_builder import ReportBuilder, _CATEGORY_MAP
from trajectory_eval.generator.rules.cycle_breaker import CycleBreakRule
from trajectory_eval.generator.rules.monotonic_progress import MonotonicProgressRule
from trajectory_eval.generator.rules.redundancy_rate import RedundancyRateRule
from trajectory_eval.generator.rules.token_efficiency import TokenEfficiencyRule
from trajectory_eval.models.contract import RuleCategory
from trajectory_eval.models.execution_report import (
    ExecutionReport,
    InconsistencyFlag,
    MetricObservation,
)


@pytest.fixture
def builder() -> ReportBuilder:
    return ReportBuilder()


class TestBuildEmptyInputs:
    """Verify correct behavior with empty metrics and/or flags."""

    def test_empty_metrics_and_flags(self, builder: ReportBuilder) -> None:
        report = builder.build(metrics_rules=[], flags=[])
        assert isinstance(report, ExecutionReport)
        assert report.metrics == []
        assert report.flags == []
        assert report.schema_version == 1
        assert report.generator.version is not None

    def test_empty_metrics_with_flags(self, builder: ReportBuilder) -> None:
        flag = InconsistencyFlag(
            target_fingerprint="interface::param_type::{}",
            category=RuleCategory.interface,
            kind="param_type",
            conflicting_constraints=[
                {"expected_type": "str"},
                {"expected_type": "int"},
            ],
            observation_count=2,
        )
        report = builder.build(metrics_rules=[], flags=[flag])
        assert report.metrics == []
        assert len(report.flags) == 1
        assert report.flags[0] == flag


class TestRedundancyRateConversion:
    """Verify RedundancyRateRule is correctly converted to MetricObservation."""

    def test_converts_redundancy_rate_rule(self, builder: ReportBuilder) -> None:
        rule = RedundancyRateRule(
            id="global_redundancy_1",
            step_index=None,
            max_rate=0.25,
            observed_rate=0.1,
            duplicate_count=2,
            total_count=20,
        )
        report = builder.build(metrics_rules=[rule], flags=[])
        assert len(report.metrics) == 1

        obs = report.metrics[0]
        assert obs.rule_class == "RedundancyRateRule"
        assert obs.category == "efficiency"
        assert obs.observation == {
            "max_rate": 0.25,
            "observed_rate": 0.1,
            "duplicate_count": 2,
            "total_count": 20,
        }


class TestTokenEfficiencyConversion:
    """Verify TokenEfficiencyRule is correctly converted to MetricObservation."""

    def test_converts_token_efficiency_rule(self, builder: ReportBuilder) -> None:
        rule = TokenEfficiencyRule(
            id="token_eff_5",
            step_index=5,
            prev_step=3,
            prev_token_count=100,
            curr_token_count=180,
            max_growth_ratio=2.0,
            observed_ratio=1.8,
        )
        report = builder.build(metrics_rules=[rule], flags=[])
        assert len(report.metrics) == 1

        obs = report.metrics[0]
        assert obs.rule_class == "TokenEfficiencyRule"
        assert obs.category == "efficiency"
        assert obs.observation == {
            "prev_step": 3,
            "prev_token_count": 100,
            "curr_token_count": 180,
            "max_growth_ratio": 2.0,
            "observed_ratio": 1.8,
        }


class TestMonotonicProgressConversion:
    """Verify MonotonicProgressRule is correctly converted to MetricObservation."""

    def test_converts_monotonic_progress_rule(self, builder: ReportBuilder) -> None:
        rule = MonotonicProgressRule(
            id="global_monotonic_4_vs_2",
            step_index=4,
            step_index_compared=2,
            stagnation_threshold=0.95,
            observed_similarity=0.87,
        )
        report = builder.build(metrics_rules=[rule], flags=[])
        assert len(report.metrics) == 1

        obs = report.metrics[0]
        assert obs.rule_class == "MonotonicProgressRule"
        assert obs.category == "progress"
        assert obs.observation == {
            "step_index_compared": 2,
            "stagnation_threshold": 0.95,
            "observed_similarity": 0.87,
        }


class TestCycleBreakConversion:
    """Verify CycleBreakRule is correctly converted to MetricObservation."""

    def test_converts_cycle_break_rule(self, builder: ReportBuilder) -> None:
        rule = CycleBreakRule(
            id="cycle_10_vs_5",
            step_index=10,
            prior_step=5,
            repeated_tool_name="read_file",
            horizon=5,
        )
        report = builder.build(metrics_rules=[rule], flags=[])
        assert len(report.metrics) == 1

        obs = report.metrics[0]
        assert obs.rule_class == "CycleBreakRule"
        assert obs.category == "efficiency"
        assert obs.observation == {
            "prior_step": 5,
            "repeated_tool_name": "read_file",
            "horizon": 5,
        }


class TestMultipleRulesAndFlags:
    """Verify mixed rule types and flags are all included in the report."""

    def test_multiple_metrics_and_flags(self, builder: ReportBuilder) -> None:
        rules = [
            RedundancyRateRule(
                id="global_redundancy_1",
                step_index=None,
                max_rate=0.25,
                observed_rate=0.05,
                duplicate_count=1,
                total_count=20,
            ),
            CycleBreakRule(
                id="cycle_8_vs_3",
                step_index=8,
                prior_step=3,
                repeated_tool_name="execute_command",
                horizon=5,
            ),
        ]
        flags = [
            InconsistencyFlag(
                target_fingerprint="workflow::tool_ordering::{}",
                category=RuleCategory.workflow,
                kind="tool_ordering",
                conflicting_constraints=[
                    {"condition": "a_succeeds"},
                    {"condition": "a_fails"},
                ],
                observation_count=4,
            ),
        ]
        report = builder.build(metrics_rules=rules, flags=flags)

        assert len(report.metrics) == 2
        assert report.metrics[0].rule_class == "RedundancyRateRule"
        assert report.metrics[1].rule_class == "CycleBreakRule"
        assert len(report.flags) == 1
        assert report.flags[0].kind == "tool_ordering"


class TestSchemaAndGeneratorFields:
    """Verify schema_version and generator are properly set."""

    def test_schema_version_is_1(self, builder: ReportBuilder) -> None:
        report = builder.build(metrics_rules=[], flags=[])
        assert report.schema_version == 1

    def test_generator_has_version(self, builder: ReportBuilder) -> None:
        report = builder.build(metrics_rules=[], flags=[])
        assert isinstance(report.generator.version, str)
        assert len(report.generator.version) > 0


class TestCategoryMapping:
    """Verify the category classification map is correct."""

    def test_redundancy_rate_is_efficiency(self) -> None:
        assert _CATEGORY_MAP[RedundancyRateRule] == "efficiency"

    def test_token_efficiency_is_efficiency(self) -> None:
        assert _CATEGORY_MAP[TokenEfficiencyRule] == "efficiency"

    def test_monotonic_progress_is_progress(self) -> None:
        assert _CATEGORY_MAP[MonotonicProgressRule] == "progress"

    def test_cycle_break_is_efficiency(self) -> None:
        assert _CATEGORY_MAP[CycleBreakRule] == "efficiency"
