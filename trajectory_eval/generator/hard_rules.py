"""Hard rule public facade.

This module is the stable public API for hard rule generation.  All
implementation logic lives in the concrete rule classes under
``trajectory_eval.generator.rules.*`` and the ``HardRuleRunner`` orchestrator.

Exported functions
------------------
generate_global_hard_rules(trajectory, embed_client, config_path)
    Trajectory-level rules a–g, driven by YAML config.

compile_contract(trajectory, embed_client, config_path)
    Single entry point producing both BehaviorContract and ExecutionReport.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from trajectory_eval.llm.azure_client import AzureFoundryClient
from trajectory_eval.models.rule import HardRule
from trajectory_eval.generator.rule_runner import HardRuleRunner

if TYPE_CHECKING:
    from trajectory_eval.generator.contract_compiler import CompilerOutput


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


async def compile_contract(
    trajectory,
    embed_client: Optional[AzureFoundryClient] = None,
    config_path: Optional[Path] = None,
) -> "CompilerOutput":
    """Compile a trajectory into a Behavior Contract and Execution Report.

    Single entry point producing both artifacts. Delegates to ContractCompiler.

    Args:
        trajectory: The full trajectory to compile.
        embed_client: Optional Azure Foundry client for embedding-based rules.
        config_path: Override path for the YAML config. Falls back to bundled default.

    Returns:
        CompilerOutput containing both BehaviorContract and ExecutionReport.
    """
    from trajectory_eval.generator.contract_compiler import (
        ContractCompiler,
        CompilerOutput,
    )  # noqa: F811

    compiler = ContractCompiler(config_path=config_path)
    return await compiler.compile(trajectory, embed_client=embed_client)
