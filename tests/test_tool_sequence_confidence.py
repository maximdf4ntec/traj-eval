"""Unit tests for the ToolSequenceRule confidence heuristic.

Validates Requirements 9.5, 9.6, 9.7, 9.8, 9.9 from the contract-redesign spec.
"""

from datetime import datetime, timezone

import pytest

from trajectory_eval.generator.rules.data_dependency import DataDependencyRule
from trajectory_eval.generator.rules.tool_sequence import (
    ToolSequenceRule,
    _PairObservation,
    _check_data_dependency_with_steps,
    _compute_confidence,
    _is_inconsistent,
)
from trajectory_eval.models.rule import ConfidenceLevel, RulePolarity
from trajectory_eval.models.trajectory import Step, StepType, Trajectory

NOW = datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# _compute_confidence tests
# ---------------------------------------------------------------------------


class TestComputeConfidence:
    """Test the three-signal confidence scoring function."""

    def test_data_flow_yields_high(self):
        """Req 9.5: Data-flow dependency → high confidence."""
        result = _compute_confidence(
            "read_file", "str_replace", 1, has_data_flow=True, powerful_couples=set()
        )
        assert result == ConfidenceLevel.high

    def test_powerful_couple_yields_high(self):
        """Req 9.6: Powerful couple → high confidence."""
        couples = {("read_file", "str_replace")}
        result = _compute_confidence(
            "read_file", "str_replace", 1, has_data_flow=False, powerful_couples=couples
        )
        assert result == ConfidenceLevel.high

    def test_count_threshold_yields_high(self):
        """Req 9.7: Count >= threshold → high confidence."""
        result = _compute_confidence(
            "tool_a",
            "tool_b",
            3,
            has_data_flow=False,
            powerful_couples=set(),
            threshold=3,
        )
        assert result == ConfidenceLevel.high

    def test_below_threshold_no_signals_yields_none(self):
        """Req 9.8: Below threshold + no signals → suppress (None)."""
        result = _compute_confidence(
            "tool_a",
            "tool_b",
            2,
            has_data_flow=False,
            powerful_couples=set(),
            threshold=3,
        )
        assert result is None

    def test_zero_occurrences_no_signals_yields_none(self):
        """Zero occurrences with no other signals → suppress."""
        result = _compute_confidence(
            "tool_a", "tool_b", 0, has_data_flow=False, powerful_couples=set()
        )
        assert result is None

    def test_data_flow_overrides_low_count(self):
        """Data-flow signal fires even with only 1 occurrence."""
        result = _compute_confidence(
            "x", "y", 1, has_data_flow=True, powerful_couples=set(), threshold=10
        )
        assert result == ConfidenceLevel.high

    def test_powerful_couple_not_in_set(self):
        """Pair not in powerful_couples set → no couple signal."""
        couples = {("create_file", "write_file")}
        result = _compute_confidence(
            "read_file", "str_replace", 1, has_data_flow=False, powerful_couples=couples
        )
        assert result is None


# ---------------------------------------------------------------------------
# _is_inconsistent tests
# ---------------------------------------------------------------------------


class TestIsInconsistent:
    """Test inconsistency detection for pair observations."""

    def test_empty_observations_is_inconsistent(self):
        assert _is_inconsistent([]) is True

    def test_all_succeed_is_consistent(self):
        obs = [_PairObservation(0, 1, 2, True), _PairObservation(3, 4, 5, True)]
        assert _is_inconsistent(obs) is False

    def test_all_fail_is_inconsistent(self):
        obs = [_PairObservation(0, 1, 2, False), _PairObservation(3, 4, 5, False)]
        assert _is_inconsistent(obs) is True

    def test_majority_succeed_is_consistent(self):
        obs = [
            _PairObservation(0, 1, 2, True),
            _PairObservation(3, 4, 5, True),
            _PairObservation(6, 7, 8, False),
        ]
        assert _is_inconsistent(obs) is False

    def test_minority_succeed_is_inconsistent(self):
        obs = [
            _PairObservation(0, 1, 2, True),
            _PairObservation(3, 4, 5, False),
            _PairObservation(6, 7, 8, False),
            _PairObservation(9, 10, 11, False),
        ]
        assert _is_inconsistent(obs) is True


# ---------------------------------------------------------------------------
# _check_data_dependency_with_steps tests
# ---------------------------------------------------------------------------


class TestCheckDataDependency:
    """Test data-flow cross-reference lookup."""

    def test_matching_data_flow(self):
        """DataDependencyRule shows tool_b consuming from tool_a → True."""
        dep_rule = DataDependencyRule(
            id="data_dep_2_path_1",
            step_index=2,
            param_key="path",
            param_value="/tmp/file.txt",
            source_step=1,
            tool_name="str_replace",
        )
        step_tool_map = {0: "read_file"}
        assert (
            _check_data_dependency_with_steps(
                "read_file", "str_replace", [dep_rule], step_tool_map
            )
            is True
        )

    def test_no_matching_source_tool(self):
        """Source step belongs to a different tool → False."""
        dep_rule = DataDependencyRule(
            id="data_dep_2_path_1",
            step_index=2,
            param_key="path",
            param_value="/tmp/file.txt",
            source_step=1,
            tool_name="str_replace",
        )
        step_tool_map = {0: "list_directory"}
        assert (
            _check_data_dependency_with_steps(
                "read_file", "str_replace", [dep_rule], step_tool_map
            )
            is False
        )

    def test_no_matching_consumer_tool(self):
        """Consumer tool doesn't match → False."""
        dep_rule = DataDependencyRule(
            id="data_dep_2_path_1",
            step_index=2,
            param_key="path",
            param_value="/tmp/file.txt",
            source_step=1,
            tool_name="write_file",
        )
        step_tool_map = {0: "read_file"}
        assert (
            _check_data_dependency_with_steps(
                "read_file", "str_replace", [dep_rule], step_tool_map
            )
            is False
        )

    def test_empty_rules_list(self):
        """No dependency rules → False."""
        assert _check_data_dependency_with_steps("a", "b", [], {0: "a"}) is False


# ---------------------------------------------------------------------------
# from_trajectory integration tests
# ---------------------------------------------------------------------------


def _make_step(index: int, step_type: StepType, **kwargs) -> Step:
    """Helper to build a Step with minimal boilerplate."""
    return Step(index=index, step_type=step_type, timestamp=NOW, **kwargs)


class TestFromTrajectory:
    """Integration tests for the full from_trajectory flow."""

    def test_suppresses_below_threshold(self):
        """Req 9.8: Single observation, no signals → no rules emitted."""
        steps = [
            _make_step(0, StepType.tool_call, tool_name="tool_a", tool_input={"x": 1}),
            _make_step(1, StepType.tool_result, tool_output="ok"),
            _make_step(2, StepType.tool_call, tool_name="tool_b", tool_input={"y": 2}),
        ]
        trajectory = Trajectory(id="test", steps=steps)
        rules = ToolSequenceRule.from_trajectory(
            trajectory, powerful_couples=set(), confidence_threshold=3
        )
        assert len(rules) == 0

    def test_emits_for_powerful_couple(self):
        """Req 9.6: Powerful couple pair → emits with high confidence."""
        steps = [
            _make_step(
                0, StepType.tool_call, tool_name="read_file", tool_input={"p": "x"}
            ),
            _make_step(1, StepType.tool_result, tool_output="content"),
            _make_step(
                2, StepType.tool_call, tool_name="str_replace", tool_input={"o": "a"}
            ),
        ]
        trajectory = Trajectory(id="test", steps=steps)
        rules = ToolSequenceRule.from_trajectory(
            trajectory,
            powerful_couples={("read_file", "str_replace")},
            confidence_threshold=3,
        )
        # Only positive rule emitted (A succeeded, no failure observed).
        assert len(rules) == 1
        assert rules[0].polarity == RulePolarity.positive
        assert all(r.confidence == ConfidenceLevel.high for r in rules)

    def test_emits_for_count_threshold(self):
        """Req 9.7: Enough observations → emits with high confidence."""
        steps = []
        for i in range(3):
            base = i * 3
            steps.extend(
                [
                    _make_step(
                        base,
                        StepType.tool_call,
                        tool_name="tool_a",
                        tool_input={"x": 1},
                    ),
                    _make_step(base + 1, StepType.tool_result, tool_output="success"),
                    _make_step(
                        base + 2,
                        StepType.tool_call,
                        tool_name="tool_b",
                        tool_input={"y": 2},
                    ),
                ]
            )
        trajectory = Trajectory(id="test", steps=steps)
        rules = ToolSequenceRule.from_trajectory(
            trajectory, powerful_couples=set(), confidence_threshold=3
        )
        # Only positive rule (all observations show A succeeding).
        assert len(rules) == 1
        assert rules[0].polarity == RulePolarity.positive
        assert all(r.confidence == ConfidenceLevel.high for r in rules)

    def test_skips_inconsistent_ordering(self):
        """Req 9.9: Inconsistent pattern → no rules emitted."""
        # All observations have A failing → inconsistent (no positive signal)
        steps = [
            _make_step(0, StepType.tool_call, tool_name="tool_a", tool_input={"x": 1}),
            _make_step(1, StepType.tool_result, tool_output="error: something failed"),
            _make_step(2, StepType.tool_call, tool_name="tool_b", tool_input={"y": 2}),
            _make_step(3, StepType.tool_call, tool_name="tool_a", tool_input={"x": 1}),
            _make_step(4, StepType.tool_result, tool_output="exception occurred"),
            _make_step(5, StepType.tool_call, tool_name="tool_b", tool_input={"y": 2}),
        ]
        trajectory = Trajectory(id="test", steps=steps)
        rules = ToolSequenceRule.from_trajectory(
            trajectory,
            powerful_couples={("tool_a", "tool_b")},
            confidence_threshold=1,
        )
        assert len(rules) == 0

    def test_yaml_list_format_for_powerful_couples(self):
        """YAML config passes list-of-lists; should be handled gracefully."""
        steps = [
            _make_step(
                0, StepType.tool_call, tool_name="read_file", tool_input={"p": "x"}
            ),
            _make_step(1, StepType.tool_result, tool_output="content"),
            _make_step(
                2, StepType.tool_call, tool_name="str_replace", tool_input={"o": "a"}
            ),
        ]
        trajectory = Trajectory(id="test", steps=steps)
        rules = ToolSequenceRule.from_trajectory(
            trajectory,
            powerful_couples=[["read_file", "str_replace"]],
            confidence_threshold=3,
        )
        # Only positive rule (success observed, no failure).
        assert len(rules) == 1
        assert rules[0].polarity == RulePolarity.positive

    def test_emits_both_polarities(self):
        """When both success and failure are observed, both polarities emit."""
        steps = []
        # 3 successful observations (meets threshold=3)
        for i in range(3):
            base = i * 3
            steps.extend(
                [
                    _make_step(
                        base, StepType.tool_call, tool_name="a", tool_input={"x": 1}
                    ),
                    _make_step(base + 1, StepType.tool_result, tool_output="ok"),
                    _make_step(
                        base + 2, StepType.tool_call, tool_name="b", tool_input={"y": 2}
                    ),
                ]
            )
        # 1 failure observation (A fails → B still follows)
        base = 9
        steps.extend(
            [
                _make_step(
                    base, StepType.tool_call, tool_name="a", tool_input={"x": 1}
                ),
                _make_step(base + 1, StepType.tool_result, tool_output="error: failed"),
                _make_step(
                    base + 2, StepType.tool_call, tool_name="b", tool_input={"y": 2}
                ),
            ]
        )
        trajectory = Trajectory(id="test", steps=steps)
        rules = ToolSequenceRule.from_trajectory(
            trajectory, powerful_couples=set(), confidence_threshold=3
        )
        polarities = {r.polarity for r in rules}
        assert RulePolarity.positive in polarities
        assert RulePolarity.negative in polarities

    def test_data_flow_signal_from_dependency_rules(self):
        """Req 9.5: Data-flow via DataDependencyRule cross-ref → high."""
        steps = [
            _make_step(
                0, StepType.tool_call, tool_name="read_file", tool_input={"path": "/x"}
            ),
            _make_step(1, StepType.tool_result, tool_output='{"path": "/x"}'),
            _make_step(
                2,
                StepType.tool_call,
                tool_name="str_replace",
                tool_input={"path": "/x"},
            ),
        ]
        trajectory = Trajectory(id="test", steps=steps)

        # DataDependencyRule showing str_replace consumes from read_file's output
        dep_rule = DataDependencyRule(
            id="data_dep_2_path_1",
            step_index=2,
            param_key="path",
            param_value="/x",
            source_step=1,
            tool_name="str_replace",
        )

        rules = ToolSequenceRule.from_trajectory(
            trajectory,
            powerful_couples=set(),
            confidence_threshold=3,
            data_dependency_rules=[dep_rule],
        )
        # Only positive rule (success observed, no failure in trajectory).
        assert len(rules) == 1
        assert rules[0].polarity == RulePolarity.positive
        assert rules[0].confidence == ConfidenceLevel.high

    def test_empty_trajectory(self):
        """Empty trajectory produces no rules."""
        trajectory = Trajectory(id="empty", steps=[])
        rules = ToolSequenceRule.from_trajectory(
            trajectory, powerful_couples=set(), confidence_threshold=3
        )
        assert len(rules) == 0
