"""Tests for the Langfuse observation-export parser."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trajectory_eval.models.trajectory import StepType, Trajectory
from trajectory_eval.parsers.langfuse import (
    _compute_latency_ms,
    _extract_cost,
    _extract_messages_from_input,
    _extract_model_params,
    _extract_output_message,
    _extract_temperature,
    _extract_token_count,
    _parse_timestamp,
    _select_generation_observations,
    parse_langfuse,
)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_space_separated_format(self) -> None:
        ts = _parse_timestamp("2026-07-16 09:07:31.538000")
        assert ts.year == 2026
        assert ts.month == 7
        assert ts.day == 16
        assert ts.hour == 9
        assert ts.minute == 7
        assert ts.second == 31
        assert ts.tzinfo == timezone.utc

    def test_iso_format(self) -> None:
        ts = _parse_timestamp("2026-07-16T09:07:31.538000")
        assert ts.year == 2026

    def test_none_returns_epoch(self) -> None:
        ts = _parse_timestamp(None)
        assert ts == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_empty_string_returns_epoch(self) -> None:
        ts = _parse_timestamp("")
        assert ts == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_invalid_returns_epoch(self) -> None:
        ts = _parse_timestamp("not-a-date")
        assert ts == datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Input/output extraction
# ---------------------------------------------------------------------------


class TestExtractMessagesFromInput:
    def test_json_string_with_messages_key(self) -> None:
        inp = json.dumps({"messages": [{"role": "user", "content": "hi"}]})
        msgs = _extract_messages_from_input(inp)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_plain_list(self) -> None:
        inp = json.dumps([{"role": "system", "content": "x"}])
        msgs = _extract_messages_from_input(inp)
        assert len(msgs) == 1

    def test_none_returns_empty(self) -> None:
        assert _extract_messages_from_input(None) == []

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_messages_from_input("") == []

    def test_dict_input_directly(self) -> None:
        inp = {"messages": [{"role": "assistant", "content": "hello"}]}
        msgs = _extract_messages_from_input(inp)
        assert len(msgs) == 1


class TestExtractOutputMessage:
    def test_direct_assistant_message(self) -> None:
        out = json.dumps(
            {
                "role": "assistant",
                "content": "Hello!",
                "tool_calls": [],
            }
        )
        msg = _extract_output_message(out)
        assert msg is not None
        assert msg["content"] == "Hello!"

    def test_with_tool_calls(self) -> None:
        out = json.dumps(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "function": {"name": "my_tool", "arguments": '{"x": 1}'},
                        "id": "call_123",
                        "type": "function",
                    }
                ],
            }
        )
        msg = _extract_output_message(out)
        assert msg is not None
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["function"]["name"] == "my_tool"

    def test_none_returns_none(self) -> None:
        assert _extract_output_message(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _extract_output_message("") is None

    def test_choices_format(self) -> None:
        out = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        )
        msg = _extract_output_message(out)
        assert msg is not None
        assert msg["content"] == "hi"


# ---------------------------------------------------------------------------
# Model parameters
# ---------------------------------------------------------------------------


class TestExtractModelParams:
    def test_json_string(self) -> None:
        params = _extract_model_params('{"temperature":"0.1","stream":false}')
        assert params["temperature"] == "0.1"
        assert params["stream"] is False

    def test_empty_string(self) -> None:
        assert _extract_model_params("") == {}

    def test_none(self) -> None:
        assert _extract_model_params(None) == {}

    def test_dict_passthrough(self) -> None:
        params = _extract_model_params({"temperature": 0.5})
        assert params["temperature"] == 0.5


class TestExtractTemperature:
    def test_string_value(self) -> None:
        assert _extract_temperature({"temperature": "0.1"}) == 0.1

    def test_float_value(self) -> None:
        assert _extract_temperature({"temperature": 0.7}) == 0.7

    def test_none_when_missing(self) -> None:
        assert _extract_temperature({}) is None

    def test_none_when_out_of_range(self) -> None:
        assert _extract_temperature({"temperature": "5.0"}) is None

    def test_zero_is_valid(self) -> None:
        assert _extract_temperature({"temperature": "0"}) == 0.0


# ---------------------------------------------------------------------------
# Latency and tokens
# ---------------------------------------------------------------------------


class TestComputeLatencyMs:
    def test_explicit_latency_field(self) -> None:
        assert _compute_latency_ms(None, None, "1633") == 1633

    def test_from_timestamps(self) -> None:
        latency = _compute_latency_ms(
            "2026-07-16 09:07:31.000000",
            "2026-07-16 09:07:33.500000",
            None,
        )
        assert latency == 2500

    def test_no_data_returns_zero(self) -> None:
        assert _compute_latency_ms(None, None, None) == 0


class TestExtractTokenCount:
    def test_uses_total_field(self) -> None:
        usage = {"input": "9879", "output": "167", "total": "12734"}
        assert _extract_token_count(usage) == 12734

    def test_sums_input_output_when_no_total(self) -> None:
        usage = {"input": "100", "output": "50"}
        assert _extract_token_count(usage) == 150

    def test_empty_dict_returns_zero(self) -> None:
        assert _extract_token_count({}) == 0


class TestExtractCost:
    def test_from_total_cost(self) -> None:
        obs = {"totalCost": 0.0084}
        assert _extract_cost(obs) == pytest.approx(0.0084)

    def test_from_cost_details(self) -> None:
        obs = {"totalCost": 0, "costDetails": {"total": 0.005}}
        assert _extract_cost(obs) == pytest.approx(0.005)

    def test_from_metadata(self) -> None:
        obs = {
            "totalCost": 0,
            "costDetails": {},
            "metadata": {"litellm_response_cost": "0.077"},
        }
        assert _extract_cost(obs) == pytest.approx(0.077)

    def test_no_cost_returns_zero(self) -> None:
        assert _extract_cost({}) == 0.0


# ---------------------------------------------------------------------------
# Observation selection
# ---------------------------------------------------------------------------


class TestSelectGenerationObservations:
    def test_filters_generations_only(self) -> None:
        obs = [
            {"type": "SPAN", "startTime": "2026-07-16 09:07:33.000000"},
            {"type": "GENERATION", "startTime": "2026-07-16 09:07:31.000000"},
            {"metadata": {}, "latencyMs": "1000"},
        ]
        gens = _select_generation_observations(obs)
        assert len(gens) == 1
        assert gens[0]["type"] == "GENERATION"

    def test_sorts_by_start_time(self) -> None:
        obs = [
            {"type": "GENERATION", "startTime": "2026-07-16 09:08:00.000000"},
            {"type": "GENERATION", "startTime": "2026-07-16 09:07:00.000000"},
        ]
        gens = _select_generation_observations(obs)
        assert gens[0]["startTime"] == "2026-07-16 09:07:00.000000"

    def test_empty_input(self) -> None:
        assert _select_generation_observations([]) == []


# ---------------------------------------------------------------------------
# Full parser integration (using the real test_michael.json)
# ---------------------------------------------------------------------------


FIXTURE_PATH = Path(__file__).resolve().parent.parent / "test_michael.json"


@pytest.fixture
def trajectory() -> Trajectory:
    """Parse the real Langfuse example file."""
    if not FIXTURE_PATH.exists():
        pytest.skip("test_michael.json not found in project root")
    return parse_langfuse(str(FIXTURE_PATH))


class TestParseLangfuseExample:
    def test_returns_trajectory_instance(self, trajectory: Trajectory) -> None:
        assert isinstance(trajectory, Trajectory)

    def test_trajectory_id_matches_filename(self, trajectory: Trajectory) -> None:
        assert trajectory.id == "test_michael"

    def test_source_platform_is_langfuse(self, trajectory: Trajectory) -> None:
        assert trajectory.source_platform == "langfuse"

    def test_agent_name_extracted(self, trajectory: Trajectory) -> None:
        assert trajectory.agent_name == "litellm-completion"

    def test_steps_are_non_empty(self, trajectory: Trajectory) -> None:
        assert len(trajectory.steps) > 0

    def test_has_tool_call_steps(self, trajectory: Trajectory) -> None:
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]
        assert len(tool_calls) >= 1

    def test_has_tool_result_steps(self, trajectory: Trajectory) -> None:
        results = [s for s in trajectory.steps if s.step_type == StepType.tool_result]
        assert len(results) >= 1

    def test_tool_call_has_real_model_name(self, trajectory: Trajectory) -> None:
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]
        assert tool_calls[0].model_name == "gpt-5.4-mini"

    def test_tool_call_has_temperature(self, trajectory: Trajectory) -> None:
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]
        assert tool_calls[0].temperature == pytest.approx(0.1)

    def test_total_cost_is_positive(self, trajectory: Trajectory) -> None:
        assert trajectory.total_cost_usd > 0

    def test_total_tokens_positive(self, trajectory: Trajectory) -> None:
        assert trajectory.total_token_count > 0

    def test_total_latency_positive(self, trajectory: Trajectory) -> None:
        assert trajectory.total_latency_ms > 0

    def test_start_time_is_real(self, trajectory: Trajectory) -> None:
        assert trajectory.start_time.year == 2026

    def test_step_indices_sequential(self, trajectory: Trajectory) -> None:
        indices = [s.index for s in trajectory.steps]
        assert indices == list(range(len(indices)))

    def test_tool_call_has_parsed_inputs(self, trajectory: Trajectory) -> None:
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]
        first = tool_calls[0]
        assert first.tool is not None
        assert len(first.tool.inputs) > 0
        keys = [inp.key for inp in first.tool.inputs]
        assert "url" in keys

    def test_tool_result_has_output(self, trajectory: Trajectory) -> None:
        results = [s for s in trajectory.steps if s.step_type == StepType.tool_result]
        if results:
            assert results[0].tool is not None
            assert results[0].tool.output is not None
            assert len(results[0].tool.output) > 0

    def test_metadata_contains_models_used(self, trajectory: Trajectory) -> None:
        assert "models_used" in trajectory.metadata
        assert "gpt-5.4-mini" in trajectory.metadata["models_used"]

    def test_tool_name_is_scraping_tool(self, trajectory: Trajectory) -> None:
        tool_calls = [s for s in trajectory.steps if s.step_type == StepType.tool_call]
        names = {s.tool.name for s in tool_calls if s.tool}
        assert "scrapfly_web_scraping_api_tool" in names


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestParseLangfuseErrors:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parse_langfuse(str(tmp_path / "nonexistent.json"))

    def test_raises_value_error_for_non_array(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text('{"not": "an array"}', encoding="utf-8")
        with pytest.raises(ValueError, match="Expected a JSON array"):
            parse_langfuse(str(f))

    def test_raises_value_error_no_generations(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text('[{"type": "SPAN", "id": "x"}]', encoding="utf-8")
        with pytest.raises(ValueError, match="No GENERATION observations"):
            parse_langfuse(str(f))

    def test_parses_minimal_generation(self, tmp_path: Path) -> None:
        """A generation with minimal fields still produces a valid trajectory."""
        gen = {
            "type": "GENERATION",
            "id": "gen-1",
            "traceId": "t-1",
            "startTime": "2026-01-01 00:00:00.000000",
            "endTime": "2026-01-01 00:00:01.000000",
            "providedModelName": "test-model",
            "modelParameters": '{"temperature":"0.5"}',
            "usageDetails": {"input": "10", "output": "5", "total": "15"},
            "costDetails": {"total": 0.001},
            "totalCost": 0.001,
            "input": json.dumps(
                {
                    "messages": [
                        {"role": "user", "content": "Hello"},
                    ]
                }
            ),
            "output": json.dumps(
                {
                    "role": "assistant",
                    "content": "Hi there!",
                    "tool_calls": [],
                }
            ),
        }
        f = tmp_path / "minimal.json"
        f.write_text(json.dumps([gen]), encoding="utf-8")

        traj = parse_langfuse(str(f))
        assert traj.id == "minimal"
        assert traj.source_platform == "langfuse"
        assert len(traj.steps) == 1
        assert traj.steps[0].step_type == StepType.llm_response
        assert traj.steps[0].response == "Hi there!"
        assert traj.steps[0].model_name == "test-model"
        assert traj.steps[0].temperature == 0.5
        assert traj.steps[0].token_count == 15
        assert traj.steps[0].cost_usd == pytest.approx(0.001)
