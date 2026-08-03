"""Langfuse observation-export parser.

Maps the Langfuse observation array format (as exported from Langfuse UI or API)
to the canonical Trajectory model.

Langfuse exports contain an array of "observations":
  - GENERATION observations: actual LLM calls with token usage, cost, model info
  - SPAN observations: logical groupings wrapping one or more generations
  - Metadata-only objects: response-level metadata (no id/type)

The parser focuses on GENERATION observations as the primary source of truth
for trajectory steps, since they contain full input/output data, token counts,
and cost information.

Data extracted beyond the base SWE-bench format:
  - Real timestamps (not synthetic)
  - Per-step latency in ms
  - Per-step token counts (input + output)
  - Per-step cost in USD
  - Model name and temperature
  - Cache hit/read token information
  - Trace hierarchy (traceId, parentObservationId)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from trajectory_eval.models.tool import Tool
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.parsers.parameter import ParserRegistry

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_timestamp(value: Optional[str]) -> datetime:
    """Parse a Langfuse timestamp string into a UTC datetime.

    Handles formats like '2026-07-16 09:07:31.538000' and ISO 8601.
    Returns epoch if the value is None or unparseable.
    """
    if not value:
        return _EPOCH
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("Could not parse timestamp: %r", value)
    return _EPOCH


def _safe_json_loads(value: Any) -> Any:
    """Attempt to parse a string as JSON; return the original if it fails."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def _extract_messages_from_input(input_field: Any) -> list[dict[str, Any]]:
    """Extract the messages list from a Langfuse observation's input field.

    The input field is typically a JSON string containing {"messages": [...]}.

    Args:
        input_field: The raw ``input`` value from an observation.

    Returns:
        The messages list, or empty list if extraction fails.
    """
    if not input_field:
        return []

    parsed = _safe_json_loads(input_field)

    if isinstance(parsed, dict):
        messages = parsed.get("messages", [])
        if isinstance(messages, list):
            return messages
    if isinstance(parsed, list):
        return parsed
    return []


def _extract_output_message(output_field: Any) -> Optional[dict[str, Any]]:
    """Extract the assistant response message from a Langfuse output field.

    The output field is typically a JSON string representing the assistant's
    response message with optional tool_calls.

    Args:
        output_field: The raw ``output`` value from an observation.

    Returns:
        The parsed assistant message dict, or None.
    """
    if not output_field:
        return None

    parsed = _safe_json_loads(output_field)

    if isinstance(parsed, dict):
        # Direct message format: {"role": "assistant", "content": ..., "tool_calls": [...]}
        if parsed.get("role") == "assistant":
            return parsed
        # Wrapped in choices: {"choices": [{"message": {...}}]}
        choices = parsed.get("choices", [])
        if choices and isinstance(choices, list):
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                return first_choice.get("message")
    return None


def _extract_model_params(model_parameters: Any) -> dict[str, Any]:
    """Parse model parameters from string or dict form.

    Args:
        model_parameters: Either a JSON string or dict of model params.

    Returns:
        Dict of parsed parameters.
    """
    if not model_parameters:
        return {}
    parsed = _safe_json_loads(model_parameters)
    return parsed if isinstance(parsed, dict) else {}


def _compute_latency_ms(
    start_time: Optional[str], end_time: Optional[str], raw_latency: Any
) -> int:
    """Compute latency in ms from timestamps or the raw latencyMs field.

    Prefers the explicit latencyMs field if present. Falls back to computing
    from end_time - start_time.
    """
    if raw_latency is not None:
        try:
            return int(raw_latency)
        except (ValueError, TypeError):
            pass

    if start_time and end_time:
        start = _parse_timestamp(start_time)
        end = _parse_timestamp(end_time)
        if start != _EPOCH and end != _EPOCH:
            delta_ms = int((end - start).total_seconds() * 1000)
            return max(0, delta_ms)
    return 0


def _extract_token_count(usage_details: dict[str, Any]) -> int:
    """Sum input + output tokens from usageDetails.

    Args:
        usage_details: Dict with string-valued token counts.

    Returns:
        Total token count (input + output).
    """
    total_str = usage_details.get("total", "0")
    try:
        total = int(total_str)
        if total > 0:
            return total
    except (ValueError, TypeError):
        pass

    input_tokens = 0
    output_tokens = 0
    try:
        input_tokens = int(usage_details.get("input", "0"))
    except (ValueError, TypeError):
        pass
    try:
        output_tokens = int(usage_details.get("output", "0"))
    except (ValueError, TypeError):
        pass
    return input_tokens + output_tokens


def _extract_cost(observation: dict[str, Any]) -> float:
    """Extract cost in USD from an observation.

    Checks totalCost first, then costDetails.total, then metadata.
    """
    total_cost = observation.get("totalCost")
    if total_cost and total_cost > 0:
        return float(total_cost)

    cost_details = observation.get("costDetails", {})
    if isinstance(cost_details, dict):
        detail_total = cost_details.get("total")
        if detail_total and detail_total > 0:
            return float(detail_total)

    metadata = observation.get("metadata", {})
    if isinstance(metadata, dict):
        litellm_cost = metadata.get("litellm_response_cost")
        if litellm_cost:
            try:
                return float(litellm_cost)
            except (ValueError, TypeError):
                pass
    return 0.0


def _extract_temperature(model_params: dict[str, Any]) -> Optional[float]:
    """Extract temperature from parsed model parameters."""
    temp = model_params.get("temperature")
    if temp is None:
        return None
    try:
        val = float(temp)
        return val if 0.0 <= val <= 2.0 else None
    except (ValueError, TypeError):
        return None


def _build_steps_from_generation(
    observation: dict[str, Any],
    registry: ParserRegistry,
) -> list[Step]:
    """Convert a single GENERATION observation into one or more Steps.

    A generation's input contains the full message history leading up to
    the LLM call. The output contains the assistant's response (possibly
    with tool_calls). We extract:
      - The conversation messages as context
      - The final assistant output as tool_call or llm_response steps

    Args:
        observation: A single Langfuse observation dict with type=GENERATION.
        registry: ParserRegistry for type-detecting tool parameters.

    Returns:
        List of Step objects extracted from this generation.
    """
    steps: list[Step] = []

    messages = _extract_messages_from_input(observation.get("input", ""))
    output_msg = _extract_output_message(observation.get("output", ""))

    start_time = _parse_timestamp(observation.get("startTime"))
    model_params = _extract_model_params(observation.get("modelParameters"))
    model_name = observation.get("providedModelName") or None
    temperature = _extract_temperature(model_params)
    latency_ms = _compute_latency_ms(
        observation.get("startTime"),
        observation.get("endTime"),
        observation.get("latencyMs"),
    )
    token_count = _extract_token_count(observation.get("usageDetails", {}))
    cost_usd = _extract_cost(observation)

    # Build metadata for the step
    step_metadata: dict[str, Any] = {
        "observation_id": observation.get("id", ""),
        "trace_id": observation.get("traceId", ""),
        "parent_observation_id": observation.get("parentObservationId", ""),
    }
    usage = observation.get("usageDetails", {})
    if usage:
        step_metadata["usage_details"] = usage
    cache_read = usage.get("cache_read_input_tokens")
    if cache_read:
        step_metadata["cache_read_input_tokens"] = cache_read

    # Extract the user prompt (last user message in the input)
    user_prompt: Optional[str] = None
    for msg in reversed(messages):
        role = msg.get("role", "")
        if role == "user":
            content = msg.get("content", "")
            user_prompt = content if isinstance(content, str) else str(content)
            break

    # Process the output message
    if output_msg is None:
        # No output — possibly an incomplete generation
        if user_prompt:
            steps.append(
                Step(
                    index=0,
                    step_type=StepType.llm_response,
                    timestamp=start_time,
                    latency_ms=latency_ms,
                    token_count=token_count,
                    cost_usd=cost_usd,
                    prompt=user_prompt,
                    response=None,
                    model_name=model_name,
                    temperature=temperature,
                    metadata=step_metadata,
                )
            )
        return steps

    tool_calls = output_msg.get("tool_calls", [])
    content = output_msg.get("content")

    if tool_calls:
        # The assistant responded with tool calls
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", {})
            tool_name = fn.get("name", "unknown_tool")
            args_raw = fn.get("arguments", "")

            # Parse arguments as JSON dict
            args_parsed = _safe_json_loads(args_raw)
            if isinstance(args_parsed, dict):
                inputs = [registry.detect(k, v) for k, v in args_parsed.items()]
            else:
                inputs = [registry.detect("arguments", args_raw)]

            tool_call_metadata = {
                **step_metadata,
                "tool_call_id": tc.get("id", ""),
                "parser_source": "native_tool_call",
            }
            if content:
                tool_call_metadata["thought"] = content

            steps.append(
                Step(
                    index=0,  # Will be re-indexed later
                    step_type=StepType.tool_call,
                    timestamp=start_time,
                    latency_ms=latency_ms,
                    token_count=token_count,
                    cost_usd=cost_usd,
                    prompt=user_prompt,
                    tool=Tool(name=tool_name, inputs=inputs),
                    model_name=model_name,
                    temperature=temperature,
                    metadata=tool_call_metadata,
                )
            )
            # Distribute cost/tokens across tool calls evenly
            if len(tool_calls) > 1:
                latency_ms = 0  # Only first tool call gets the latency
                token_count = 0
                cost_usd = 0.0
    else:
        # Plain LLM response (no tool calls)
        response_text = content if isinstance(content, str) else None
        steps.append(
            Step(
                index=0,
                step_type=StepType.llm_response,
                timestamp=start_time,
                latency_ms=latency_ms,
                token_count=token_count,
                cost_usd=cost_usd,
                prompt=user_prompt,
                response=response_text,
                model_name=model_name,
                temperature=temperature,
                metadata=step_metadata,
            )
        )

    # Also extract tool_result steps from the input messages
    # (tool responses in the conversation history)
    for msg in messages:
        if msg.get("role") == "tool":
            tool_content = msg.get("content", "")
            tool_name = msg.get("name", "")
            tool_call_id = msg.get("tool_call_id", "")

            output_typed_param = registry.detect("output", tool_content)
            output_typed_param = output_typed_param.model_copy(
                update={"direction": "output"}
            )

            steps.append(
                Step(
                    index=0,
                    step_type=StepType.tool_result,
                    timestamp=start_time,
                    tool=Tool(
                        name=tool_name,
                        output=(
                            tool_content
                            if isinstance(tool_content, str)
                            else str(tool_content)
                        ),
                        output_typed=output_typed_param,
                    ),
                    metadata={
                        "tool_call_id": tool_call_id,
                        "observation_id": observation.get("id", ""),
                    },
                )
            )

    return steps


def _select_generation_observations(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter and sort GENERATION observations by startTime.

    Args:
        observations: Raw list of all observation dicts.

    Returns:
        GENERATION observations sorted chronologically.
    """
    generations = [
        obs
        for obs in observations
        if isinstance(obs, dict) and obs.get("type") == "GENERATION"
    ]
    generations.sort(key=lambda o: _parse_timestamp(o.get("startTime")))
    return generations


def _collect_trace_metadata(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate trace-level metadata from all observations.

    Extracts overall cost, token usage, model info, and timing from
    metadata-only objects and SPAN observations.
    """
    meta: dict[str, Any] = {}
    total_cost = 0.0
    total_tokens = 0
    models_used: list[str] = []

    for obs in observations:
        if not isinstance(obs, dict):
            continue

        # Collect from metadata-only objects (no id, no type)
        if "id" not in obs and "type" not in obs:
            obs_meta = obs.get("metadata", {})
            if isinstance(obs_meta, dict):
                # Extract rate limit info from hidden_params
                hidden = _safe_json_loads(obs_meta.get("hidden_params", "{}"))
                if isinstance(hidden, dict):
                    model_name = hidden.get("litellm_model_name")
                    if model_name and model_name not in models_used:
                        models_used.append(model_name)
                    meta["api_base"] = obs_meta.get("api_base", "")

        # Aggregate costs from GENERATION observations
        if obs.get("type") == "GENERATION":
            total_cost += _extract_cost(obs)
            total_tokens += _extract_token_count(obs.get("usageDetails", {}))
            model = obs.get("providedModelName")
            if model and model not in models_used:
                models_used.append(model)

    meta["models_used"] = models_used
    meta["total_cost_usd"] = total_cost
    meta["total_tokens"] = total_tokens
    return meta


def parse_langfuse(file_path: str) -> Trajectory:
    """Parse a Langfuse observation export JSON and return a canonical Trajectory.

    The input file should be a JSON array of observation objects, as exported
    from Langfuse's UI or fetched via the Langfuse API.

    Args:
        file_path: Absolute or relative path to the JSON file.

    Returns:
        A fully populated :class:`Trajectory` instance with real timestamps,
        token counts, costs, and model information.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be parsed or has no GENERATION observations.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Trajectory file not found: {file_path}")

    raw: Any = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, list):
        raise ValueError(
            f"Expected a JSON array in '{file_path}', got {type(raw).__name__}"
        )

    generations = _select_generation_observations(raw)
    if not generations:
        raise ValueError(
            f"No GENERATION observations found in '{file_path}'. "
            "Ensure the file contains Langfuse observation data."
        )

    registry = ParserRegistry()
    all_steps: list[Step] = []

    for gen_obs in generations:
        gen_steps = _build_steps_from_generation(gen_obs, registry)
        all_steps.extend(gen_steps)

    # Re-index steps sequentially
    for idx, step in enumerate(all_steps):
        step.index = idx

    # Link tool_result output back to preceding tool_call steps
    for i, step in enumerate(all_steps):
        if step.step_type == StepType.tool_result and step.tool is not None:
            # Find the matching tool_call by tool_call_id or position
            result_tc_id = step.metadata.get("tool_call_id", "")
            for prev_step in reversed(all_steps[:i]):
                if (
                    prev_step.step_type == StepType.tool_call
                    and prev_step.tool is not None
                ):
                    prev_tc_id = prev_step.metadata.get("tool_call_id", "")
                    if result_tc_id and prev_tc_id == result_tc_id:
                        prev_step.tool.output = step.tool.output
                        prev_step.tool.output_typed = step.tool.output_typed
                        break
                    elif not result_tc_id:
                        # Positional fallback
                        prev_step.tool.output = step.tool.output
                        prev_step.tool.output_typed = step.tool.output_typed
                        break

    # Compute trajectory-level aggregates
    trace_meta = _collect_trace_metadata(raw)
    trajectory_id = path.stem

    n = len(all_steps)
    start_time = all_steps[0].timestamp if n > 0 else _EPOCH
    end_time = all_steps[-1].timestamp if n > 0 else _EPOCH
    total_latency = sum(s.latency_ms for s in all_steps)
    total_tokens = sum(s.token_count for s in all_steps)
    total_cost = sum(s.cost_usd for s in all_steps)

    # Determine agent name from trace name
    agent_name: Optional[str] = None
    for obs in raw:
        if isinstance(obs, dict):
            tn = obs.get("traceName")
            if tn:
                agent_name = tn
                break

    return Trajectory(
        id=trajectory_id,
        source_platform="langfuse",
        agent_name=agent_name,
        start_time=start_time,
        end_time=end_time,
        total_latency_ms=total_latency,
        total_token_count=total_tokens,
        total_cost_usd=total_cost,
        steps=all_steps,
        metadata=trace_meta,
    )
