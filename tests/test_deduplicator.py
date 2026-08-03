"""Unit tests for trajectory_eval.generator.deduplicator."""

from __future__ import annotations

import pytest

from trajectory_eval.generator.deduplicator import (
    DeduplicationResult,
    RuleDeduplicator,
    _max_confidence,
)
from trajectory_eval.models.contract import (
    CompiledRule,
    RuleCardinality,
    RuleCategory,
    RuleMetadata,
    RuleTarget,
)
from trajectory_eval.models.execution_report import InconsistencyFlag
from trajectory_eval.models.rule import ConfidenceLevel


def _make_rule(
    *,
    id: str = "tmp_001",
    category: RuleCategory = RuleCategory.interface,
    kind: str = "param_type",
    tool: str = "str_replace",
    parameter: str | None = "old_str",
    constraint: dict | None = None,
    cardinality: RuleCardinality = RuleCardinality.all,
    confidence: ConfidenceLevel = ConfidenceLevel.medium,
    support: int = 1,
) -> CompiledRule:
    """Factory helper to build a CompiledRule for testing."""
    return CompiledRule(
        id=id,
        category=category,
        kind=kind,
        target=RuleTarget(tool=tool, parameter=parameter),
        constraint=constraint or {"expected_type": "str"},
        cardinality=cardinality,
        metadata=RuleMetadata(confidence=confidence, support=support),
    )


class TestMaxConfidence:
    """Tests for the _max_confidence helper."""

    def test_single_high(self) -> None:
        assert _max_confidence([ConfidenceLevel.high]) == ConfidenceLevel.high

    def test_mixed_returns_highest(self) -> None:
        levels = [ConfidenceLevel.low, ConfidenceLevel.medium, ConfidenceLevel.high]
        assert _max_confidence(levels) == ConfidenceLevel.high

    def test_all_low(self) -> None:
        assert (
            _max_confidence([ConfidenceLevel.low, ConfidenceLevel.low])
            == ConfidenceLevel.low
        )

    def test_medium_beats_low(self) -> None:
        assert (
            _max_confidence([ConfidenceLevel.low, ConfidenceLevel.medium])
            == ConfidenceLevel.medium
        )


class TestRuleDeduplicator:
    """Tests for the RuleDeduplicator class."""

    def setup_method(self) -> None:
        self.deduplicator = RuleDeduplicator()

    def test_empty_input(self) -> None:
        result = self.deduplicator.deduplicate([])
        assert result.rules == []
        assert result.flags == []

    def test_single_rule_passthrough(self) -> None:
        rule = _make_rule()
        result = self.deduplicator.deduplicate([rule])

        assert len(result.rules) == 1
        assert result.rules[0].id == "rule_001"
        assert result.rules[0].metadata.support == 1
        # Support=1 caps confidence at low regardless of input.
        assert result.rules[0].metadata.confidence == ConfidenceLevel.low
        assert result.flags == []

    def test_identical_rules_merged(self) -> None:
        """Two rules with same identity and constraint merge to one with support=2."""
        rules = [
            _make_rule(id="tmp_001", confidence=ConfidenceLevel.low),
            _make_rule(id="tmp_002", confidence=ConfidenceLevel.high),
        ]
        result = self.deduplicator.deduplicate(rules)

        assert len(result.rules) == 1
        merged = result.rules[0]
        assert merged.id == "rule_001"
        assert merged.metadata.support == 2
        # Support=2 caps at medium (high downgraded).
        assert merged.metadata.confidence == ConfidenceLevel.medium
        assert merged.constraint == {"expected_type": "str"}
        assert result.flags == []

    def test_conflicting_constraints_produce_flag(self) -> None:
        """Rules with same identity but different constraints produce a flag."""
        rules = [
            _make_rule(id="tmp_001", constraint={"expected_type": "str"}),
            _make_rule(id="tmp_002", constraint={"expected_type": "int"}),
        ]
        result = self.deduplicator.deduplicate(rules)

        assert len(result.rules) == 0
        assert len(result.flags) == 1
        flag = result.flags[0]
        assert flag.category == RuleCategory.interface
        assert flag.kind == "param_type"
        assert flag.observation_count == 2
        assert {"expected_type": "str"} in flag.conflicting_constraints
        assert {"expected_type": "int"} in flag.conflicting_constraints

    def test_sequential_ids(self) -> None:
        """Deduplicated rules get sequential rule_001, rule_002, etc. IDs."""
        rules = [
            _make_rule(id="a", tool="tool_a", parameter="p1"),
            _make_rule(id="b", tool="tool_b", parameter="p2"),
            _make_rule(id="c", tool="tool_c", parameter="p3"),
        ]
        result = self.deduplicator.deduplicate(rules)

        assert len(result.rules) == 3
        assert result.rules[0].id == "rule_001"
        assert result.rules[1].id == "rule_002"
        assert result.rules[2].id == "rule_003"

    def test_different_targets_not_merged(self) -> None:
        """Rules with different targets are kept separate."""
        rules = [
            _make_rule(id="a", tool="read_file", parameter="path"),
            _make_rule(id="b", tool="write_file", parameter="path"),
        ]
        result = self.deduplicator.deduplicate(rules)

        assert len(result.rules) == 2
        assert result.flags == []

    def test_identity_key_canonical(self) -> None:
        """Identity key is deterministic regardless of field order."""
        rule = _make_rule(tool="foo", parameter="bar")
        key = self.deduplicator._identity_key(rule)
        assert "interface" in key
        assert "param_type" in key
        assert "foo" in key
        assert "bar" in key

    def test_result_is_dataclass(self) -> None:
        """DeduplicationResult is a proper dataclass."""
        result = DeduplicationResult()
        assert result.rules == []
        assert result.flags == []

    def test_merge_preserves_category_and_kind(self) -> None:
        """Merged rule preserves the category and kind from the group."""
        rules = [
            _make_rule(
                category=RuleCategory.provenance,
                kind="data_lineage",
                constraint={
                    "must_originate_from": {
                        "tool": "read_file",
                        "output_field": "__OUTPUT__",
                    }
                },
            ),
            _make_rule(
                category=RuleCategory.provenance,
                kind="data_lineage",
                constraint={
                    "must_originate_from": {
                        "tool": "read_file",
                        "output_field": "__OUTPUT__",
                    }
                },
            ),
        ]
        result = self.deduplicator.deduplicate(rules)

        assert len(result.rules) == 1
        assert result.rules[0].category == RuleCategory.provenance
        assert result.rules[0].kind == "data_lineage"
        assert result.rules[0].metadata.support == 2

    def test_mixed_consistent_and_inconsistent(self) -> None:
        """Groups are handled independently — some merge, some flag."""
        rules = [
            # These two are consistent (same target, same constraint)
            _make_rule(id="a", tool="tool_a", constraint={"type": "str"}),
            _make_rule(id="b", tool="tool_a", constraint={"type": "str"}),
            # These two are inconsistent (same target, different constraint)
            _make_rule(id="c", tool="tool_b", constraint={"type": "int"}),
            _make_rule(id="d", tool="tool_b", constraint={"type": "bool"}),
        ]
        result = self.deduplicator.deduplicate(rules)

        assert len(result.rules) == 1
        assert result.rules[0].metadata.support == 2
        assert len(result.flags) == 1
        assert result.flags[0].observation_count == 2
