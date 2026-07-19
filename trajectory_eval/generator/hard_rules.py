"""Hard rule public facade.

This module is the stable public API for hard rule generation.  All
implementation logic lives in the concrete rule classes under
``trajectory_eval.generator.rules.*`` and the ``HardRuleRunner`` orchestrator.

Exported functions
------------------
generate_global_hard_rules(trajectory, embed_client, config_path)
    Trajectory-level rules a–g, driven by YAML config.

tool_call_rules(step)
    Per-step rules h (parameter count + types) and i (tool index).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from trajectory_eval.llm.azure_client import AzureFoundryClient
from trajectory_eval.models.rule import HardRule
from trajectory_eval.models.trajectory import Step
from trajectory_eval.generator.rule_runner import HardRuleRunner
from trajectory_eval.generator.rules import (
    ToolIndexRule,
    ToolParamCountRule,
    ToolParamTypeRule,
)


async def generate_global_hard_rules(
    trajectory,
    embed_client: Optional[AzureFoundryClient] = None,
    config_path: Optional[Path] = None,
) -> list[HardRule]:
    """Generate all trajectory-level hard rules (a through g).

    Delegates to :class:`~trajectory_eval.generator.rule_runner.HardRuleRunner`
    which reads the YAML config and dispatches to each concrete rule class.

    Args:
        trajectory: The full trajectory to analyse.
        embed_client: Optional Azure Foundry client for Rule b (embedding).
            Rule b is silently skipped when None.
        config_path: Override path for the YAML threshold configuration.
            Falls back to the bundled ``hard_rules_config.yaml`` when None.

    Returns:
        Ordered list of HardRule instances covering rules a-g.
    """
    runner = HardRuleRunner(config_path=config_path)
    return await runner.run(trajectory, embed_client=embed_client)


def tool_call_rules(step: Step) -> list[HardRule]:
    """Generate per-step hard rules h (parameter types) and i (tool index).

    Args:
        step: A Step of type ``tool_call``.

    Returns:
        A list of HardRule instances: one ToolIndexRule plus, for each
        parameter, a ToolParamCountRule and one ToolParamTypeRule.
    """
    rules: list[HardRule] = [ToolIndexRule.from_step(step)]

    if not step.tool_input:
        return rules

    rules.append(ToolParamCountRule.from_step(step))
    for key, val in step.tool_input.items():
        rules.append(ToolParamTypeRule.from_step(step, param_key=key, param_value=val))

    return rules
