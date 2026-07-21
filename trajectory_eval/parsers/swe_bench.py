"""SWE-bench .traj file parser.

Maps the SWE-bench trajectory message format to the canonical Trajectory model.

The parser handles multiple tool-call formats:
  - Native tool_calls (OpenAI / Anthropic spec)
  - Markdown fenced code blocks (tool name inferred from first word)
  - Inline command prefixes (heuristic fallback)

Turn-to-step mapping
--------------------
role: system                          → skip
role: user  (first / task text)       → user_message   (content → prompt)
role: assistant  (has tool calls)     → tool_call per identified call
role: user  (after tool call)         → tool_result    (content → tool_output)
role: assistant  (no tool calls)      → llm_response   (content → response)

Synthetic timestamps: Unix epoch + step_index seconds.
Cost / tokens: 0.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trajectory_eval.models.tool import Tool
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.parsers.parameter import ParserRegistry

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_COMMON_TOOLS = [
    "str_replace_editor",
    "view_file",
    "open_file",
    "find",
    "grep",
    "python",
    "pytest",
    "git",
    "cd",
    "ls",
    "cat",
]


def _epoch_plus(seconds: int) -> datetime:
    """Return a datetime that is *seconds* after the Unix epoch."""
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def extract_text_content(content: Any) -> str:
    """Extract raw string content from messages.

    Handles both plain strings and block lists
    (e.g. ``[{'type': 'text', 'text': '...'}]``).

    Args:
        content: The raw ``content`` field of a message dict.

    Returns:
        A single joined string, or empty string when nothing is found.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        extracted_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                for key in ("text", "content", "value"):
                    if key in block and isinstance(block[key], str):
                        extracted_parts.append(block[key])
                        break
            elif isinstance(block, str):
                extracted_parts.append(block)
        return "\n".join(extracted_parts)
    return ""


def identify_tool_calls(message: dict) -> list[dict[str, str]]:
    """Heuristically parse an assistant message to identify tool calls.

    Checks in priority order:
    1. Native ``tool_calls`` array (OpenAI / Anthropic spec).
    2. Markdown fenced code blocks — tool name inferred from first word.
    3. Lines starting with a known tool name (fallback).

    Args:
        message: A single message dict from the trajectory.

    Returns:
        A list of dicts with keys ``parser_source``, ``tool_name``,
        and ``arguments``.
    """
    tool_calls: list[dict[str, str]] = []

    # Priority 1: structured native tool calls
    if message.get("tool_calls"):
        for tc in message["tool_calls"]:
            if isinstance(tc, dict):
                name = tc.get("function", {}).get(
                    "name", tc.get("name", "unknown_tool")
                )
                args = tc.get("function", {}).get("arguments", tc.get("arguments", ""))
                tool_calls.append(
                    {
                        "parser_source": "native_tool_call",
                        "tool_name": name,
                        "arguments": args,
                    }
                )
        if tool_calls:
            return tool_calls

    text_content = extract_text_content(message.get("content", ""))

    # Priority 2: markdown fenced code blocks
    bt = "`" * 3
    pattern = rf"{bt}(?:[a-zA-Z0-9_-]+)?\n(.*?)\n{bt}"
    for block in re.findall(pattern, text_content, re.DOTALL):
        clean_block = block.strip()
        if clean_block:
            parts = clean_block.split()
            first_word = parts[0] if parts else "command"
            tool_calls.append(
                {
                    "parser_source": "markdown_code_block",
                    "tool_name": first_word,
                    "arguments": clean_block,
                }
            )

    if tool_calls:
        return tool_calls

    # Priority 3: un-fenced lines beginning with a known tool name
    for line in text_content.splitlines():
        line_stripped = line.strip()
        for tool in _COMMON_TOOLS:
            if line_stripped.startswith(tool):
                tool_calls.append(
                    {
                        "parser_source": "inline_prefix",
                        "tool_name": tool,
                        "arguments": line_stripped,
                    }
                )
                break

    return tool_calls


def clean_observation(message: dict) -> str:
    """Extract response text and strip standard observation prefix decorators.

    Args:
        message: A user / tool message dict from the trajectory.

    Returns:
        The cleaned observation string.
    """
    text = extract_text_content(message.get("content", ""))
    for prefix in (r"^OBSERVATION:\s*", r"^Observation:\s*", r"^\[Observation\]\s*"):
        text = re.sub(prefix, "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_single_trajectory(messages: list[dict]) -> list[dict]:
    """Chronologically structure a conversation into execution steps.

    Each returned step dict has keys:
    * ``thought`` – the assistant's raw text content (``None`` for initial user steps).
    * ``tool_calls`` – list of tool-call dicts (may be empty).
    * ``response`` – the following observation / user reply (``None`` if absent).

    Args:
        messages: Raw message list from the trajectory file.

    Returns:
        A list of step dicts ready for conversion to :class:`Step` objects.
    """
    steps: list[dict] = []
    current_step: dict | None = None

    for msg in messages:
        role = str(msg.get("role", msg.get("from", ""))).lower()

        if role in ("assistant", "agent", "gpt"):
            tool_calls = identify_tool_calls(msg)
            current_step = {
                "thought": extract_text_content(msg.get("content", "")),
                "tool_calls": tool_calls,
                "response": None,
            }
            steps.append(current_step)

        elif role in ("user", "human", "tool", "observation"):
            response_text = clean_observation(msg)
            if current_step is not None:
                current_step["response"] = response_text
            else:
                steps.append(
                    {
                        "thought": None,
                        "tool_calls": [],
                        "response": response_text,
                    }
                )

    return steps


def _extract_messages(raw: Any, file_path: str) -> list[dict[str, Any]]:
    """Extract the list of chat messages from the raw parsed JSON.

    Supported layouts:
    * Top-level list (the messages array itself).
    * Dict with a ``history``, ``messages``, or ``trajectory`` key whose
      value is a list.

    Args:
        raw: Parsed JSON value.
        file_path: Original file path (used in error messages only).

    Returns:
        The list of message dicts.

    Raises:
        ValueError: When no messages list can be located.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("history", "messages", "trajectory"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(
        f"Cannot locate a messages list in '{file_path}'. "
        "Expected a JSON array or a JSON object with a 'history' / "
        "'messages' / 'trajectory' key."
    )


def parse_swe_bench(file_path: str) -> Trajectory:
    """Parse a SWE-bench .traj file and return a canonical Trajectory.

    Args:
        file_path: Absolute or relative path to the ``.traj`` file.

    Returns:
        A fully populated :class:`Trajectory` instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be parsed or has an unrecognised layout.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Trajectory file not found: {file_path}")

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    all_messages = _extract_messages(raw, file_path)

    # Skip system messages before handing off to the generic parser.
    messages = [
        m for m in all_messages if isinstance(m, dict) and m.get("role") != "system"
    ]

    trajectory_id = path.stem

    parsed_steps = parse_single_trajectory(messages)

    registry = ParserRegistry()

    steps: list[Step] = []
    step_index = 0

    for parsed in parsed_steps:
        thought: str | None = parsed["thought"]
        tool_calls: list[dict] = parsed["tool_calls"]
        response: str | None = parsed["response"]

        if thought is None:
            # Initial user / problem description message.
            steps.append(
                Step(
                    index=step_index,
                    step_type=StepType.user_message,
                    timestamp=_epoch_plus(step_index),
                    prompt=response,
                )
            )
            step_index += 1

        elif tool_calls:
            # One Step per identified tool call.
            for tc in tool_calls:
                tool_input_dict = {"command": tc["arguments"]}
                inputs = [registry.detect(k, v) for k, v in tool_input_dict.items()]
                steps.append(
                    Step(
                        index=step_index,
                        step_type=StepType.tool_call,
                        timestamp=_epoch_plus(step_index),
                        tool=Tool(name=tc["tool_name"], inputs=inputs),
                        metadata={
                            "parser_source": tc.get("parser_source", ""),
                            "thought": thought,
                        },
                    )
                )
                step_index += 1

            if response is not None:
                # Run type detection on the output for the typed representation
                output_typed_param = registry.detect("output", response)
                output_typed_param = output_typed_param.model_copy(
                    update={"direction": "output"}
                )

                # Find the preceding tool_call's tool name for the tool_result step
                prev_tool_name = ""
                for s in reversed(steps):
                    if s.step_type == StepType.tool_call and s.tool is not None:
                        prev_tool_name = s.tool.name
                        break

                steps.append(
                    Step(
                        index=step_index,
                        step_type=StepType.tool_result,
                        timestamp=_epoch_plus(step_index),
                        tool=Tool(
                            name=prev_tool_name,
                            output=response,
                            output_typed=output_typed_param,
                        ),
                    )
                )
                step_index += 1
                # Attach output to the preceding tool_call step's tool
                for s in reversed(steps[:-1]):
                    if s.step_type == StepType.tool_call and s.tool is not None:
                        s.tool.output = response
                        s.tool.output_typed = output_typed_param
                        break

        else:
            # No tool calls — plain LLM response.
            steps.append(
                Step(
                    index=step_index,
                    step_type=StepType.llm_response,
                    timestamp=_epoch_plus(step_index),
                    response=thought,
                )
            )
            step_index += 1

    n = len(steps)
    return Trajectory(
        id=trajectory_id,
        source_platform="swe_bench",
        start_time=_epoch_plus(0) if n > 0 else _EPOCH,
        end_time=_epoch_plus(n - 1) if n > 0 else _EPOCH,
        steps=steps,
    )
