"""Integration tests for DataDependencyRule through the full contract pipeline.

These tests verify that lineage rules survive the emit → deduplicate pipeline,
particularly when a single consuming tool receives data from multiple source tools
(which is the common case for type-based rules).

The bug scenario: type-based rules generate DataDependencyRules with the same
(tool_name, param_key) target but different source_tool_name values. After emission,
the deduplicator groups them by target and sees different constraints (different
'must_originate_from' dicts), treating them as inconsistencies → 0 output rules.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trajectory_eval.generator.deduplicator import RuleDeduplicator
from trajectory_eval.generator.emitter import emit
from trajectory_eval.generator.rules.data_dependency import DataDependencyRule
from trajectory_eval.models.contract import RuleCategory
from trajectory_eval.models.rule import ConfidenceLevel
from trajectory_eval.models.tool import (
    ParameterType,
    Tool,
    ToolParameter,
)
from trajectory_eval.models.trajectory import (
    Step,
    StepType,
    Trajectory,
)

_DT = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _make_dep_rule(
    *,
    step_index: int,
    param_key: str,
    tool_name: str,
    source_tool_name: str,
    source_step: int,
    confidence: ConfidenceLevel = ConfidenceLevel.high,
    param_value: str = "/some/path",
) -> DataDependencyRule:
    return DataDependencyRule(
        id=f"data_dep_{step_index}_{param_key}_{source_step}",
        step_index=step_index,
        param_key=param_key,
        param_value=param_value,
        source_step=source_step,
        source_tool_name=source_tool_name,
        tool_name=tool_name,
        confidence=confidence,
    )


class TestDataDependencyEmitDedup:
    """Tests for the emit → dedup pipeline with DataDependencyRules."""

    def test_single_source_produces_rule(self) -> None:
        """A single lineage rule should survive emit + dedup."""
        rule = _make_dep_rule(
            step_index=4,
            param_key="path",
            tool_name="read_file",
            source_tool_name="list_directory",
            source_step=2,
        )
        compiled = emit(rule)
        dedup = RuleDeduplicator()
        result = dedup.deduplicate([compiled])

        assert len(result.rules) == 1
        assert result.flags == []

    def test_multiple_sources_same_target_all_survive(self) -> None:
        """Multiple lineage rules for the same (tool, param) but different sources
        must all survive deduplication — they are different invariants.

        This is the critical test that catches the bug: before the fix,
        these rules share a dedup identity key and have conflicting constraints,
        resulting in 0 output rules and an inconsistency flag.
        """
        rules = [
            _make_dep_rule(
                step_index=4,
                param_key="command",
                tool_name="python",
                source_tool_name="str_replace_editor",
                source_step=2,
            ),
            _make_dep_rule(
                step_index=6,
                param_key="command",
                tool_name="python",
                source_tool_name="find",
                source_step=1,
            ),
        ]
        compiled = [emit(r) for r in rules]
        dedup = RuleDeduplicator()
        result = dedup.deduplicate(compiled)

        # Both should survive — they describe different provenance relationships
        assert len(result.rules) >= 2, (
            f"Expected at least 2 lineage rules but got {len(result.rules)}. "
            f"Flags: {len(result.flags)}. "
            "Rules with different source tools should not conflict."
        )
        assert len(result.flags) == 0, (
            f"Expected no inconsistency flags but got {len(result.flags)}. "
            "Different source tools are NOT inconsistencies."
        )

    def test_type_based_and_value_based_coexist(self) -> None:
        """Value-based and type-based rules for the same tool/param but different
        sources must both survive deduplication.
        """
        value_rule = _make_dep_rule(
            step_index=4,
            param_key="command",
            tool_name="python",
            source_tool_name="str_replace_editor",
            source_step=2,
            confidence=ConfidenceLevel.high,
            param_value="/path/to/file.py",
        )
        type_rule = _make_dep_rule(
            step_index=4,
            param_key="command",
            tool_name="python",
            source_tool_name="find",
            source_step=1,
            confidence=ConfidenceLevel.potential,
            param_value="type:file_path",
        )
        compiled = [emit(value_rule), emit(type_rule)]
        dedup = RuleDeduplicator()
        result = dedup.deduplicate(compiled)

        # Both should exist — different source tools = different invariants
        assert len(result.rules) >= 2, (
            f"Expected at least 2 rules but got {len(result.rules)}. "
            f"Flags: {len(result.flags)}."
        )
        assert len(result.flags) == 0

    def test_same_source_merges_correctly(self) -> None:
        """Multiple rules with same (tool, param, source) SHOULD merge to one
        with increased support.
        """
        rules = [
            _make_dep_rule(
                step_index=4,
                param_key="command",
                tool_name="python",
                source_tool_name="str_replace_editor",
                source_step=2,
            ),
            _make_dep_rule(
                step_index=6,
                param_key="command",
                tool_name="python",
                source_tool_name="str_replace_editor",
                source_step=3,
            ),
        ]
        compiled = [emit(r) for r in rules]
        dedup = RuleDeduplicator()
        result = dedup.deduplicate(compiled)

        # Same source → should merge into one rule with support=2
        assert len(result.rules) == 1
        assert result.rules[0].metadata.support == 2
        assert result.flags == []


class TestEndToEndLineageProduction:
    """End-to-end test: trajectory → from_trajectory → emit → dedup → rules."""

    def test_full_pipeline_produces_lineage_rules(self) -> None:
        """A realistic trajectory must produce non-zero lineage rules
        through the full pipeline.
        """
        # Step 0: tool_call list_files
        step0 = Step(
            index=0,
            step_type=StepType.tool_call,
            timestamp=_DT,
            tool=Tool(
                name="list_files",
                inputs=[
                    ToolParameter(
                        key="directory",
                        raw_value="/src",
                        detected_type=ParameterType.file_path,
                    )
                ],
            ),
        )
        # Step 1: tool_result from list_files (outputs file paths)
        step1 = Step(
            index=1,
            step_type=StepType.tool_result,
            timestamp=_DT,
            tool=Tool(
                name="list_files",
                inputs=[],
                output="/src/main.py\n/src/utils.py",
                output_typed=ToolParameter(
                    key="output",
                    raw_value="/src/main.py\n/src/utils.py",
                    detected_type=ParameterType.file_path,
                    direction="output",
                ),
            ),
        )
        # Step 2: tool_call read_file consuming a path from list_files output
        step2 = Step(
            index=2,
            step_type=StepType.tool_call,
            timestamp=_DT,
            tool=Tool(
                name="read_file",
                inputs=[
                    ToolParameter(
                        key="path",
                        raw_value="/src/main.py",
                        detected_type=ParameterType.file_path,
                    )
                ],
            ),
        )
        # Step 3: tool_result from read_file
        step3 = Step(
            index=3,
            step_type=StepType.tool_result,
            timestamp=_DT,
            tool=Tool(
                name="read_file",
                inputs=[],
                output="def main(): pass",
                output_typed=ToolParameter(
                    key="output",
                    raw_value="def main(): pass",
                    detected_type=ParameterType.code,
                    direction="output",
                ),
            ),
        )
        # Step 4: tool_call str_replace consuming code from read_file
        step4 = Step(
            index=4,
            step_type=StepType.tool_call,
            timestamp=_DT,
            tool=Tool(
                name="str_replace",
                inputs=[
                    ToolParameter(
                        key="file_path",
                        raw_value="/src/main.py",
                        detected_type=ParameterType.file_path,
                    ),
                    ToolParameter(
                        key="old_str",
                        raw_value="def main(): pass",
                        detected_type=ParameterType.code,
                    ),
                ],
            ),
        )

        traj = Trajectory(id="test_pipeline", steps=[step0, step1, step2, step3, step4])

        # Run full pipeline
        raw_rules = DataDependencyRule.from_trajectory(traj)
        assert len(raw_rules) > 0, "from_trajectory should produce rules"

        # Emit all
        compiled = [emit(r) for r in raw_rules]
        assert len(compiled) > 0

        # Deduplicate
        dedup = RuleDeduplicator()
        result = dedup.deduplicate(compiled)

        # The critical assertion: lineage rules must survive deduplication
        assert len(result.rules) > 0, (
            f"Expected lineage rules to survive dedup but got 0. "
            f"Raw rules: {len(raw_rules)}, Compiled: {len(compiled)}, "
            f"Flags: {len(result.flags)}. "
            "Lineage rules are being incorrectly flagged as inconsistencies."
        )

        # Verify they're provenance/lineage rules
        for r in result.rules:
            assert r.category == RuleCategory.provenance
            assert r.kind == "data_lineage"
