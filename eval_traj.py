"""CLI entry point for the Trajectory Evaluation System MVP.

Usage
-----
    python eval_traj.py path/to/trajectory.traj

Output
------
A JSON array printed to stdout.  Each element is a serialised
:class:`~trajectory_eval.models.rule.Rule` dict with keys::

    {
      "id":               "<step_type>_<step_index>_<seq>",
      "step_index":       <int | null>,
      "rule_type":        "hard" | "soft",
      "polarity":         "positive" | "negative",
      "scope":            "step" | "frame" | "global",
      "step_type":        "tool_call" | "tool_result" | "llm_response" | ...,
      "confidence":       "high" | "medium" | "low",
      "rule_description": "<plain English>",
      "pseudocode":       "<human-readable logic>"
    }"

Environment variables (all optional — LLM calls are skipped gracefully on failure)
-----------------------------------------------------------------------------------
    AZURE_FOUNDRY_ENDPOINT   Base URL for Azure AI Foundry, e.g.
                             https://<resource>.services.ai.azure.com/models
    AZURE_FOUNDRY_KEY        API key / Bearer token.
    AZURE_FOUNDRY_MODEL      Model name (default: DeepSeek-V4-0).
    TOOL_CONTEXT_WINDOW      Preceding steps included in tool-pair LLM prompt
                             (default: 3).
"""

# TODO
# 1. Add more hard rules (end trajectory, llm related rules)
# 1.1 - Terminal state check                ✅ TerminalStateRule (terminal_state.py)
# 1.2 - Grounding/referential integrity     ✅ LlmGroundingRule  (llm_grounding.py)
# 1.3 - output type check                   ✅ ToolResultTypeRule (tool_result_type.py)
# 1.4 - Format/schema conformance           ✅ LlmResponseFormatRule (llm_format.py)
# 1.5 - Numeric cross-check
# 2. Run on different trajectories and check the output
# 3. Add optimizer to remove duplicate rules and improve the quality of rules
# 4. Add support for running on multiple trajectories (not a single run), how to learn and improve
# 4.1 Basic mechanism - add "trajectory dna to the test set" - embedding of the initial user prompt  + list of tools used
# 4.2 Might need checks for all trajectory specific rules (those using tool name or prompt)
# 5. Add support for golden path and compare the generated rules with the golden path rules to see if they match
# 6. Generate python code
# 6.1 - check prompt signature and skip if not matching
# 6.2 - intelligently handle missing tools - notify only once
# 7. Connect to Langfuse UI
# 7.1 - Display trajectory steps and applied rules candidates + confidence
# 7.2 - Allow approve / reject rules and save the approved rules to a file
# 7.3 - Ask questions about the trajectory and steps??
# 7.4 - allow mark required / optional steps
# 8. Finalize failed vs successful trajectory rules and how to handle them
from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from trajectory_eval.generator.hard_rules import (
    generate_global_hard_rules,
    tool_call_rules,
)
from trajectory_eval.generator.soft_rules import (
    generate_llm_response_soft_rule,
    generate_tool_result_soft_rules,
)
from trajectory_eval.llm.azure_client import AzureFoundryClient
from trajectory_eval.models.rule import Rule
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.parsers.swe_bench import parse_swe_bench


def _format_trajectory(trajectory: Trajectory) -> str:
    """Format the trajectory for display with all key information per step.

    For each step, displays:
    - user_message: first 100 characters of prompt
    - tool_call: tool name and parameters
    - tool_result: tool name and first 100 characters of output
    - llm_response: first 100 characters of response

    Args:
        trajectory: The trajectory to format.

    Returns:
        A formatted string representation of the trajectory.
    """
    lines = [
        f"\n{'='*80}",
        f"TRAJECTORY: {trajectory.id} ({len(trajectory.steps)} steps)",
        f"Platform: {trajectory.source_platform}",
        f"{'='*80}\n",
    ]

    for step in trajectory.steps:
        idx_str = f"[Step {step.index:2d}]"

        if step.step_type == StepType.user_message:
            prompt_preview = (step.prompt or "")[:100]
            if len(step.prompt or "") > 100:
                prompt_preview += "..."
            lines.append(f"{idx_str} USER_MESSAGE:")
            lines.append(f"    {prompt_preview}")

        elif step.step_type == StepType.tool_call:
            tool_input_str = str(step.tool_input or {})
            if len(tool_input_str) > 100:
                tool_input_str = tool_input_str[:97] + "..."
            lines.append(f"{idx_str} TOOL_CALL: {step.tool_name}")
            lines.append(f"    Args: {tool_input_str}")

        elif step.step_type == StepType.tool_result:
            tool_name = (
                step.metadata.get("tool_name", "unknown")
                if step.metadata
                else "unknown"
            )
            output_preview = (step.tool_output or "")[:100]
            if len(step.tool_output or "") > 100:
                output_preview += "..."
            lines.append(f"{idx_str} TOOL_RESULT:")
            lines.append(f"    {output_preview}")

        elif step.step_type == StepType.llm_response:
            response_preview = (step.response or "")[:100]
            if len(step.response or "") > 100:
                response_preview += "..."
            lines.append(f"{idx_str} LLM_RESPONSE:")
            lines.append(f"    {response_preview}")

        elif step.step_type == StepType.error:
            error_preview = (step.error_message or "")[:100]
            if len(step.error_message or "") > 100:
                error_preview += "..."
            lines.append(f"{idx_str} ERROR:")
            lines.append(f"    {error_preview}")

    lines.append(f"\n{'='*80}\n")
    return "\n".join(lines)


def _find_preceding_tool_call(
    trajectory: Trajectory, tool_result_index: int
) -> Optional[Step]:
    """Return the tool_call step immediately before *tool_result_index*, or None."""
    for step in reversed(trajectory.steps):
        if step.index < tool_result_index and step.step_type == StepType.tool_call:
            return step
    return None


async def evaluate(traj_path: str) -> list[Rule]:
    """Parse the trajectory and generate all rules.

    Args:
        traj_path: Path to the ``.traj`` file.

    Returns:
        Ordered list of :class:`~trajectory_eval.models.rule.Rule` instances
        (hard rules first, then soft rules, per step).
    """
    trajectory = parse_swe_bench(traj_path)

    # Print formatted trajectory for inspection.
    print(_format_trajectory(trajectory), file=sys.stderr)

    llm_client = AzureFoundryClient()
    all_rules: list[Rule] = []

    # Trajectory-level hard rules (a–g).
    all_rules.extend(
        await generate_global_hard_rules(trajectory, embed_client=llm_client)
    )

    for step in trajectory.steps:
        if step.step_type == StepType.tool_call:
            # Per-step hard rules h (param types) and i (tool index).
            all_rules.extend(tool_call_rules(step))

        # elif step.step_type == StepType.tool_result:
        #     # Soft rules (combined tool-pair LLM call).
        #     tool_call_step = _find_preceding_tool_call(trajectory, step.index)
        #     if tool_call_step is not None:
        #         soft = await generate_tool_result_soft_rules(
        #             trajectory, tool_call_step, step, llm_client
        #         )
        #         all_rules.extend(soft)

        # elif step.step_type == StepType.llm_response:
        #     # Hard-coded soft rule — no LLM call.
        #     all_rules.append(generate_llm_response_soft_rule(step))

    return all_rules


def main() -> None:
    """CLI entry point: parse arguments, run evaluation, print JSON."""
    if len(sys.argv) != 2:
        print(
            "Usage: python eval_traj.py path/to/trajectory.traj",
            file=sys.stderr,
        )
        sys.exit(1)

    traj_path = sys.argv[1]

    try:
        rules = asyncio.run(evaluate(traj_path))
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        json.dumps(
            [r.model_dump(mode="json") for r in rules], indent=2, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
