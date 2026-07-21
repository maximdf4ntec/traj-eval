"""Tests for the SWE-bench trajectory parser (trajectory_eval.parsers.swe_bench).

Uses example_traj.json as the reference fixture.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from trajectory_eval.models.trajectory import StepType, Trajectory
from trajectory_eval.parsers.swe_bench import (
    clean_observation,
    extract_text_content,
    identify_tool_calls,
    parse_swe_bench,
    parse_single_trajectory,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_EXAMPLE_TRAJ = _REPO_ROOT / "example_traj.json"


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestExtractTextContent:
    def test_plain_string_passthrough(self):
        assert extract_text_content("hello") == "hello"

    def test_none_returns_empty(self):
        assert extract_text_content(None) == ""

    def test_list_of_text_blocks(self):
        blocks = [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]
        result = extract_text_content(blocks)
        assert "foo" in result
        assert "bar" in result

    def test_list_with_text_key(self):
        blocks = [{"text": "hello world"}]
        assert extract_text_content(blocks) == "hello world"

    def test_list_with_content_key(self):
        blocks = [{"content": "from content key"}]
        assert extract_text_content(blocks) == "from content key"

    def test_list_of_plain_strings(self):
        assert extract_text_content(["a", "b"]) == "a\nb"

    def test_empty_list(self):
        assert extract_text_content([]) == ""


class TestIdentifyToolCalls:
    def test_native_tool_calls_openai_spec(self):
        msg = {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "my_tool", "arguments": '{"x": 1}'}}],
        }
        calls = identify_tool_calls(msg)
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "my_tool"
        assert calls[0]["parser_source"] == "native_tool_call"

    def test_native_tool_calls_flat_spec(self):
        msg = {
            "role": "assistant",
            "tool_calls": [{"name": "flat_tool", "arguments": "arg"}],
        }
        calls = identify_tool_calls(msg)
        assert calls[0]["tool_name"] == "flat_tool"

    def test_markdown_code_block_infers_tool_name(self):
        msg = {
            "role": "assistant",
            "content": "Here is the command:\n```\nfind /testbed -name '*.py'\n```",
        }
        calls = identify_tool_calls(msg)
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "find"
        assert calls[0]["parser_source"] == "markdown_code_block"

    def test_markdown_code_block_with_language_hint(self):
        msg = {
            "role": "assistant",
            "content": "Run this:\n```bash\npython setup.py test\n```",
        }
        calls = identify_tool_calls(msg)
        assert calls[0]["tool_name"] == "python"

    def test_multiple_code_blocks(self):
        msg = {
            "role": "assistant",
            "content": "First:\n```\nfind /tmp\n```\nThen:\n```\ngrep -r foo /tmp\n```",
        }
        calls = identify_tool_calls(msg)
        assert len(calls) == 2
        assert calls[0]["tool_name"] == "find"
        assert calls[1]["tool_name"] == "grep"

    def test_inline_prefix_fallback(self):
        msg = {"role": "assistant", "content": "git status"}
        calls = identify_tool_calls(msg)
        assert any(c["tool_name"] == "git" for c in calls)
        assert all(c["parser_source"] == "inline_prefix" for c in calls)

    def test_no_tool_calls_returns_empty(self):
        msg = {"role": "assistant", "content": "Just a plain response with no tools."}
        assert identify_tool_calls(msg) == []

    def test_native_takes_priority_over_markdown(self):
        msg = {
            "role": "assistant",
            "content": "```\nfind /tmp\n```",
            "tool_calls": [{"name": "native_tool", "arguments": ""}],
        }
        calls = identify_tool_calls(msg)
        assert calls[0]["parser_source"] == "native_tool_call"
        assert calls[0]["tool_name"] == "native_tool"


class TestCleanObservation:
    def test_removes_observation_prefix(self):
        msg = {"content": "OBSERVATION:\n/testbed/file.py"}
        assert clean_observation(msg) == "/testbed/file.py"

    def test_removes_lowercase_observation_prefix(self):
        msg = {"content": "Observation: some result"}
        assert clean_observation(msg) == "some result"

    def test_removes_bracket_observation_prefix(self):
        msg = {"content": "[Observation] found it"}
        assert clean_observation(msg) == "found it"

    def test_no_prefix_returned_as_is(self):
        msg = {"content": "plain content"}
        assert clean_observation(msg) == "plain content"

    def test_empty_content(self):
        assert clean_observation({}) == ""


class TestParseSingleTrajectory:
    def test_initial_user_message_captured(self):
        messages = [
            {"role": "user", "content": "Fix the bug"},
            {"role": "assistant", "content": "```\nfind /src\n```"},
            {"role": "user", "content": "OBSERVATION:\n/src/main.py"},
        ]
        steps = parse_single_trajectory(messages)
        # First step: initial user message (before any assistant)
        assert steps[0]["thought"] is None
        assert "Fix the bug" in steps[0]["response"]

    def test_tool_call_step_structure(self):
        messages = [
            {"role": "assistant", "content": "Run this:\n```\ngrep foo /tmp\n```"},
            {"role": "user", "content": "OBSERVATION:\nfoo.py:10: foo"},
        ]
        steps = parse_single_trajectory(messages)
        assert steps[0]["tool_calls"][0]["tool_name"] == "grep"
        assert "foo.py" in steps[0]["response"]

    def test_response_linked_to_preceding_assistant_step(self):
        messages = [
            {"role": "assistant", "content": "```\nls /tmp\n```"},
            {"role": "user", "content": "OBSERVATION:\nfile.txt"},
        ]
        steps = parse_single_trajectory(messages)
        assert len(steps) == 1
        assert steps[0]["response"] == "file.txt"

    def test_llm_response_no_tool_calls(self):
        messages = [
            {"role": "assistant", "content": "The answer is 42."},
        ]
        steps = parse_single_trajectory(messages)
        assert steps[0]["tool_calls"] == []
        assert steps[0]["thought"] == "The answer is 42."

    def test_system_messages_excluded(self):
        # parse_single_trajectory does NOT skip system — that's done upstream,
        # but system messages are neither assistant nor user/human so they are
        # silently ignored.
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "assistant", "content": "Hello!"},
        ]
        steps = parse_single_trajectory(messages)
        assert len(steps) == 1


# ===========================================================================
# Integration test using example_traj.json
# ===========================================================================


class TestParseSWEBenchExample:
    @pytest.fixture(scope="class")
    def trajectory(self) -> Trajectory:
        return parse_swe_bench(str(_EXAMPLE_TRAJ))

    def test_returns_trajectory_instance(self, trajectory):
        assert isinstance(trajectory, Trajectory)

    def test_trajectory_id_matches_filename(self, trajectory):
        assert trajectory.id == "example_traj"

    def test_source_platform_is_swe_bench(self, trajectory):
        assert trajectory.source_platform == "swe_bench"

    def test_steps_are_non_empty(self, trajectory):
        assert len(trajectory.steps) > 0

    def test_first_step_is_user_message(self, trajectory):
        assert trajectory.steps[0].step_type == StepType.user_message

    def test_user_message_has_prompt(self, trajectory):
        first = trajectory.steps[0]
        assert first.prompt is not None
        assert len(first.prompt) > 0

    def test_tool_calls_are_not_all_bash(self, trajectory):
        tool_names = {s.tool_name for s in trajectory.steps if s.tool_name}
        assert (
            "bash" not in tool_names
        ), "All tool calls are named 'bash' — the old parser logic is still active."

    def test_contains_expected_tool_names(self, trajectory):
        tool_names = {s.tool_name for s in trajectory.steps if s.tool_name}
        # The example trajectory uses str_replace_editor and python heavily.
        assert "str_replace_editor" in tool_names
        assert "python" in tool_names

    def test_step_types_are_valid(self, trajectory):
        valid_types = set(StepType)
        for step in trajectory.steps:
            assert step.step_type in valid_types

    def test_step_indices_are_sequential(self, trajectory):
        for i, step in enumerate(trajectory.steps):
            assert step.index == i

    def test_tool_call_steps_have_tool_name(self, trajectory):
        for step in trajectory.steps:
            if step.step_type == StepType.tool_call:
                assert step.tool is not None
                assert step.tool.name is not None
                assert step.tool.name != ""

    def test_tool_call_steps_have_tool_input(self, trajectory):
        for step in trajectory.steps:
            if step.step_type == StepType.tool_call:
                assert step.tool is not None
                assert len(step.tool.inputs) > 0
                # The swe_bench parser always produces a "command" param
                input_keys = {p.key for p in step.tool.inputs}
                assert "command" in input_keys

    def test_tool_call_steps_record_parser_source(self, trajectory):
        valid_sources = {"native_tool_call", "markdown_code_block", "inline_prefix"}
        for step in trajectory.steps:
            if step.step_type == StepType.tool_call:
                src = step.metadata.get("parser_source", "")
                assert src in valid_sources, f"Unexpected parser_source: {src!r}"

    def test_tool_result_steps_have_tool_output(self, trajectory):
        for step in trajectory.steps:
            if step.step_type == StepType.tool_result:
                # tool_output may be empty string for empty observations but
                # the field must exist (not None).
                assert step.tool_output is not None

    def test_timestamps_are_sequential(self, trajectory):
        ts = [s.timestamp for s in trajectory.steps]
        assert ts == sorted(ts)

    def test_start_and_end_times(self, trajectory):
        assert trajectory.start_time <= trajectory.end_time

    def test_no_bash_tool_name_in_step_type_tool_call(self, trajectory):
        bash_steps = [
            s
            for s in trajectory.steps
            if s.step_type == StepType.tool_call and s.tool.name == "bash"
        ]
        assert bash_steps == [], f"Found {len(bash_steps)} steps still labelled 'bash'"

    def test_step_counts_by_type(self, trajectory):
        counts = Counter(s.step_type for s in trajectory.steps)
        # Must have at least one of each primary type.
        assert counts[StepType.user_message] >= 1
        assert counts[StepType.tool_call] >= 1
        assert counts[StepType.tool_result] >= 1


# ===========================================================================
# Error handling tests
# ===========================================================================


class TestParseSWEBenchErrors:
    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_swe_bench(str(tmp_path / "nonexistent.traj"))

    def test_raises_value_error_for_invalid_layout(self, tmp_path):
        bad = tmp_path / "bad.traj"
        bad.write_text(json.dumps({"not_a_known_key": 42}), encoding="utf-8")
        with pytest.raises(ValueError):
            parse_swe_bench(str(bad))

    def test_parses_dict_with_messages_key(self, tmp_path):
        traj = tmp_path / "wrapped.traj"
        traj.write_text(
            json.dumps(
                {
                    "messages": [
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "```\nfind /tmp\n```"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = parse_swe_bench(str(traj))
        assert isinstance(result, Trajectory)
        assert any(s.step_type == StepType.tool_call for s in result.steps)

    def test_parses_dict_with_history_key(self, tmp_path):
        traj = tmp_path / "history.traj"
        traj.write_text(
            json.dumps(
                {
                    "history": [
                        {"role": "user", "content": "do something"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = parse_swe_bench(str(traj))
        assert isinstance(result, Trajectory)
