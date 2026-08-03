"""CLI entry point for the Trajectory Evaluation System.

Usage
-----
    python eval_traj.py path/to/trajectory.traj

Output
------
A JSON object printed to stdout containing both artifacts:

    {
      "contract": { ... BehaviorContract schema v2 ... },
      "report":   { ... ExecutionReport ... }
    }

The contract contains step-agnostic, deduplicated invariants.
The report contains metrics observations and inconsistency flags.

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
# ✅ 1. Add more hard rules (end trajectory, llm related rules)
# 1.1 - Terminal state check                ✅ TerminalStateRule (terminal_state.py)
# 1.2 - Grounding/referential integrity     ✅ LlmGroundingRule  (llm_grounding.py)
# 1.3 - output type check                   ✅ ToolResultTypeRule (tool_result_type.py)
# 1.4 - Format/schema conformance           ✅ LlmResponseFormatRule (llm_format.py)
# 1.5 - Numeric cross-check ?
# 2. Run on different trajectories and check the output
# ✅ 3. Add optimizer to remove duplicate rules and improve the quality of rules - Done
# 4. Add support for running on multiple trajectories (not a single run), how to learn and improve
# 4.1 Basic mechanism - add "trajectory dna to the test set" - embedding of the initial user prompt  + list of tools used
# 4.2 Might need checks for all trajectory specific rules (those using tool name or prompt)
# 5. Implement Performance contract
# ✅5.1 Basic rules
# 5.2 Add Prompt DNA for performance rules (future?)
# ✅7. Implement Additional parser for langfuse format
# 8. Add support for golden path / multiple trajectories
# 11. Generate python code
# 11.1 - check prompt signature and skip if not matching
# 11.2 - intelligently handle missing tools - notify only once
# 12. Generate OpenClaw / Hermes hooks
# 13. Generate evals
# 14. Connect to Langfuse UI
# 15.1 - Display trajectory steps and applied rules candidates + confidence
# 15.2 - Allow approve / reject rules and save the approved rules to a file
# 15.3 - Ask questions about the trajectory and steps??
# 15.4 - allow mark required / optional steps
# 16. Generate CLI interface
# 17. Finalize failed vs successful trajectory rules and how to handle them

from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from trajectory_eval.generator.hard_rules import compile_contract
from trajectory_eval.llm.azure_client import AzureFoundryClient
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.parsers.swe_bench import parse_swe_bench
from trajectory_eval.parsers.langfuse import parse_langfuse


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


def _auto_parse(traj_path: str) -> Trajectory:
    """Auto-detect trajectory format and parse with the appropriate parser.

    Detection heuristic:
      - If the JSON is an array and any element has "type": "GENERATION",
        it's a Langfuse observation export.
      - Otherwise, fall back to the SWE-bench message-list parser.

    Args:
        traj_path: Path to the trajectory file.

    Returns:
        A parsed Trajectory instance.
    """
    from pathlib import Path

    path = Path(traj_path)
    if not path.exists():
        raise FileNotFoundError(f"Trajectory file not found: {traj_path}")

    raw = json.loads(path.read_text(encoding="utf-8"))

    # Detect Langfuse format: array of observations with "type" field
    if isinstance(raw, list) and any(
        isinstance(item, dict) and item.get("type") in ("GENERATION", "SPAN")
        for item in raw
    ):
        return parse_langfuse(traj_path)

    return parse_swe_bench(traj_path)


def _find_preceding_tool_call(
    trajectory: Trajectory, tool_result_index: int
) -> Optional[Step]:
    """Return the tool_call step immediately before *tool_result_index*, or None."""
    for step in reversed(trajectory.steps):
        if step.index < tool_result_index and step.step_type == StepType.tool_call:
            return step
    return None


async def evaluate(traj_path: str) -> dict:
    """Parse the trajectory and compile the behavior contract + execution report.

    Automatically detects the format (Langfuse observation export vs SWE-bench
    messages) based on file content.

    Args:
        traj_path: Path to the trajectory file (.traj or .json).

    Returns:
        Dict with 'contract' and 'report' keys, each JSON-serializable.
    """
    trajectory = _auto_parse(traj_path)

    # Print formatted trajectory for inspection.
    print(_format_trajectory(trajectory), file=sys.stderr)

    llm_client = AzureFoundryClient()

    # Compile trajectory into BehaviorContract + ExecutionReport.
    output = await compile_contract(trajectory, embed_client=llm_client)

    return {
        "contract": output.contract.model_dump(mode="json", exclude_none=True),
        "report": output.report.model_dump(mode="json", exclude_none=True),
    }


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
        result = asyncio.run(evaluate(traj_path))
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
