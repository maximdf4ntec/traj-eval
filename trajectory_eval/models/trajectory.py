"""Trajectory and Step Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from trajectory_eval.models.tool import Tool


class StepType(str, Enum):
    """Classification of a single step in an agent trajectory."""

    user_message = "user_message"
    llm_response = "llm_response"
    tool_call = "tool_call"
    tool_result = "tool_result"
    error = "error"


class Step(BaseModel):
    """A single node in a trajectory representing one interaction unit.

    Attributes:
        index: Zero-based position in the trajectory.
        step_type: Classification of this step.
        timestamp: When this step occurred (UTC).
        latency_ms: Duration in milliseconds.
        token_count: Tokens consumed (0 when unknown).
        cost_usd: Estimated cost in USD (0.0 when unknown).
        prompt: Input text for LLM / user steps (None for other types).
        response: LLM output text (None for non-LLM steps).
        tool: Structured tool invocation (non-None for tool_call and tool_result steps).
        error_message: Error description for error steps (None otherwise).
        model_name: LLM model identifier (None for non-LLM steps).
        temperature: Sampling temperature used (None for non-LLM steps).
        metadata: Arbitrary additional data.
    """

    index: int
    step_type: StepType
    timestamp: datetime
    latency_ms: int = 0
    token_count: int = 0
    cost_usd: float = 0.0

    prompt: Optional[str] = None
    response: Optional[str] = None
    tool: Optional[Tool] = None
    error_message: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    metadata: dict[str, Any] = {}

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: Optional[float]) -> Optional[float]:
        """Ensure temperature is in the valid range [0.0, 2.0]."""
        if v is not None and not (0.0 <= v <= 2.0):
            raise ValueError(f"temperature must be in [0.0, 2.0], got {v}")
        return v

    @property
    def tool_name(self) -> Optional[str]:
        """Name of the invoked tool (derived from tool field)."""
        return self.tool.name if self.tool else None

    @property
    def tool_input(self) -> Optional[dict[str, Any]]:
        """Arguments passed to the tool as a dict (derived from tool.inputs)."""
        if self.tool is None:
            return None
        return {p.key: p.raw_value for p in self.tool.inputs}

    @property
    def tool_output(self) -> Optional[str]:
        """Raw output from the tool invocation (reads from tool.output).

        For tool_call and tool_result steps with a tool reference, returns
        the tool's output string. For other steps, returns None.
        """
        return self.tool.output if self.tool else None

    @property
    def tool_output_parsed(self) -> Optional[dict[str, Any]]:
        """Parse tool_output as JSON dict, or None if absent / invalid.

        Reads from tool.output via the tool_output property.
        """
        output = self.tool_output
        if not output:
            return None
        import json  # noqa: PLC0415 — local import to keep module light

        try:
            parsed = json.loads(output)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None


class Trajectory(BaseModel):
    """Complete record of an agent execution.

    Attributes:
        id: Unique non-empty identifier (typically derived from file name).
        source_platform: Platform that produced this trajectory.
        agent_name: Optional name of the agent.
        start_time: UTC timestamp of the first step.
        end_time: UTC timestamp of the last step.
        total_latency_ms: Sum of all step latencies in milliseconds.
        total_token_count: Sum of all token counts.
        total_cost_usd: Estimated total cost in USD.
        steps: Ordered list of steps.
        metadata: Arbitrary additional data.
    """

    id: str
    source_platform: str = "swe_bench"
    agent_name: Optional[str] = None
    start_time: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)
    end_time: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)
    total_latency_ms: int = 0
    total_token_count: int = 0
    total_cost_usd: float = 0.0
    steps: list[Step] = []
    metadata: dict[str, Any] = {}

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, v: str) -> str:
        if not v:
            raise ValueError("Trajectory id must be a non-empty string")
        return v
