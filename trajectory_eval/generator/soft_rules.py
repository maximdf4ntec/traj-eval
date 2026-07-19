"""Soft rule generator - one LLM call per tool_result step.

For each ``tool_result`` step the generator sends a single combined prompt
that asks the model to evaluate:

1. **tool_call_appropriateness** - was this the right tool with the right
   arguments given the preceding trajectory context?
2. **result_plausibility** - does the result plausibly follow from the inputs?

Context window is controlled by the ``TOOL_CONTEXT_WINDOW`` env var
(default 3 preceding steps).

For ``llm_response`` steps a hard-coded soft rule is returned without any
LLM call:
  "The response is relevant to and consistent with the task."

On any LLM failure (timeout, auth error, malformed JSON) the function falls
back to template descriptions so the pipeline never crashes.
"""

from __future__ import annotations

import json
import logging
import os

from trajectory_eval.llm.azure_client import AzureFoundryClient, _extract_json_from_text
from trajectory_eval.models.rule import ConfidenceLevel, RulePolarity, RuleScope, SoftRule
from trajectory_eval.models.trajectory import Step, StepType, Trajectory

_log = logging.getLogger(__name__)

_CONTEXT_WINDOW: int = int(os.getenv("TOOL_CONTEXT_WINDOW", "3"))

_FALLBACK_APPROPRIATENESS = (
    "The tool selected with the given arguments was a reasonable choice "
    "given the preceding trajectory context."
)
_FALLBACK_PLAUSIBILITY = (
    "The tool result plausibly follows from the tool input provided."
)


def _build_context_summary(steps: list[Step], before_index: int, window: int) -> str:
    """Summarise up to *window* steps immediately before *before_index*.

    Args:
        steps: Full ordered list of steps in the trajectory.
        before_index: Index of the step that is **not** included (exclusive end).
        window: Maximum number of preceding steps to include.

    Returns:
        A multi-line human-readable summary, or "(no preceding context)".
    """
    start = max(0, before_index - window)
    context_steps = steps[start:before_index]
    if not context_steps:
        return "(no preceding context)"

    lines: list[str] = []
    for s in context_steps:
        if s.step_type == StepType.tool_call:
            keys = list(s.tool_input.keys()) if s.tool_input else []
            lines.append(
                f"[{s.index}] tool_call: tool={s.tool_name!r}, input_keys={keys}"
            )
        elif s.step_type == StepType.tool_result:
            preview = (s.tool_output or "")[:120]
            lines.append(f"[{s.index}] tool_result: output_preview={preview!r}")
        elif s.step_type == StepType.user_message:
            preview = (s.prompt or "")[:120]
            lines.append(f"[{s.index}] user_message: prompt={preview!r}")
        elif s.step_type == StepType.llm_response:
            preview = (s.response or "")[:120]
            lines.append(f"[{s.index}] llm_response: response={preview!r}")
        else:
            lines.append(f"[{s.index}] {s.step_type.value}")

    return "\n".join(lines)


def _build_tool_pair_prompt(
    trajectory: Trajectory,
    tool_call_step: Step,
    tool_result_step: Step,
    context_window: int,
) -> str:
    """Build the combined tool-pair evaluation prompt.

    Args:
        trajectory: Full trajectory (used for context window lookup).
        tool_call_step: The step that invoked the tool.
        tool_result_step: The step that contains the tool output.
        context_window: Number of preceding steps to include.

    Returns:
        A formatted prompt string.
    """
    context = _build_context_summary(
        trajectory.steps, tool_call_step.index, context_window
    )
    tool_input_str = (
        json.dumps(tool_call_step.tool_input, indent=2)
        if tool_call_step.tool_input
        else "null"
    )
    # Truncate long outputs to keep the prompt manageable.
    tool_output_preview = (tool_result_step.tool_output or "")[:800]

    return f"""You are evaluating a step in an LLM agent trajectory.

Preceding context ({context_window} steps before the tool call):
{context}

Tool call (step {tool_call_step.index}):
  Tool name : {tool_call_step.tool_name!r}
  Tool input: {tool_input_str}

Tool result (step {tool_result_step.index}):
  Output    : {tool_output_preview!r}

Respond with a JSON object containing exactly these two keys:
{{
  "tool_call_appropriateness": "<up to 300 chars: was this tool call appropriate given the context, on four criteria: tool-goal fit, argument grounding, non-redundancy, ordering correctness?>",
  "result_plausibility": "<up to 300 chars: does the result plausibly follow from the tool input?>"
}}"""


async def generate_tool_result_soft_rules(
    trajectory: Trajectory,
    tool_call_step: Step,
    tool_result_step: Step,
    llm_client: AzureFoundryClient,
    context_window: int = _CONTEXT_WINDOW,
) -> list[SoftRule]:
    """Generate two soft rules for a tool_call + tool_result pair via LLM.

    On any LLM failure the function falls back to template descriptions so
    that the overall pipeline never crashes.

    Args:
        trajectory: Full trajectory for context window resolution.
        tool_call_step: The ``tool_call`` step.
        tool_result_step: The ``tool_result`` step.
        llm_client: Configured Azure Foundry client.
        context_window: Preceding steps to include in the prompt.

    Returns:
        A list of exactly two :class:`~trajectory_eval.models.rule.SoftRule`
        instances.
    """
    prompt = _build_tool_pair_prompt(
        trajectory, tool_call_step, tool_result_step, context_window
    )

    appropriateness = _FALLBACK_APPROPRIATENESS
    plausibility = _FALLBACK_PLAUSIBILITY

    try:
        raw_response = await llm_client.complete(prompt, timeout=30.0)
        data = _extract_json_from_text(raw_response)
        appropriateness = str(
            data.get("tool_call_appropriateness", _FALLBACK_APPROPRIATENESS)
        )[:300]
        plausibility = str(data.get("result_plausibility", _FALLBACK_PLAUSIBILITY))[
            :300
        ]
    except Exception as exc:
        _log.warning(
            "LLM call failed for step %d; using fallback text. Error: %s",
            tool_result_step.index,
            exc,
        )

    return [
        SoftRule(
            id=f"tool_result_{tool_result_step.index}_soft_1",
            step_index=tool_result_step.index,
            polarity=RulePolarity.positive,
            scope=RuleScope.frame,
            step_type=StepType.tool_result,
            confidence=ConfidenceLevel.medium,
            rule_description=appropriateness,
            pseudocode=(
                f"The tool call at step {tool_call_step.index} was appropriate "
                "given the preceding trajectory context."
            ),
        ),
        SoftRule(
            id=f"tool_result_{tool_result_step.index}_soft_2",
            step_index=tool_result_step.index,
            polarity=RulePolarity.positive,
            scope=RuleScope.frame,
            step_type=StepType.tool_result,
            confidence=ConfidenceLevel.medium,
            rule_description=plausibility,
            pseudocode=(
                f"The tool result at step {tool_result_step.index} plausibly "
                "follows from the tool input provided."
            ),
        ),
    ]


def generate_llm_response_soft_rule(step: Step) -> SoftRule:
    """Return the single hard-coded soft rule for an ``llm_response`` step.

    No LLM call is made for this rule - the description is fixed by the spec.

    Args:
        step: A Step of type ``llm_response``.

    Returns:
        A :class:`~trajectory_eval.models.rule.SoftRule` instance.
    """
    return SoftRule(
        id=f"llm_response_{step.index}_soft_1",
        step_index=step.index,
        polarity=RulePolarity.positive,
        scope=RuleScope.step,
        step_type=StepType.llm_response,
        confidence=ConfidenceLevel.medium,
        rule_description="The response is relevant to and consistent with the task.",
        pseudocode=(
            f"step[{step.index}].response is relevant to and consistent with the task."
        ),
    )