"""HardRuleRunner — reads YAML config and dispatches to concrete rule classes.

The runner is the *only* component that reads ``hard_rules_config.yaml``.
All other modules obtain rules through ``generate_global_hard_rules`` in
``hard_rules.py``, which delegates to this class.

YAML layout expected::

    failure_keywords:
      - error
      - ...

    rules:
      redundancy_rate:
        enabled: true
        max_rate: 0.25
      monotonic_progress:
        enabled: true
        ...

The ``rules`` keys must match the keys in ``_REGISTRY`` below.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Optional

import yaml

from trajectory_eval.llm.azure_client import AzureFoundryClient
from trajectory_eval.models.rule import HardRule
from trajectory_eval.models.trajectory import Trajectory
from trajectory_eval.generator.rules import (
    CycleBreakRule,
    DataDependencyRule,
    MonotonicProgressRule,
    MutationMatcherRule,
    RedundancyRateRule,
    TokenEfficiencyRule,
    ToolSequenceRule,
    ToolIndexRule,
    ToolParamCountRule,
    ToolParamTypeRule,
    TerminalStateRule,
    ToolResultTypeRule,
    LlmResponseFormatRule,
    LlmGroundingRule,
)

_log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "hard_rules_config.yaml"

# Maps YAML rule keys to their concrete rule classes.
# Each class must implement a ``from_trajectory(trajectory, **params)``
# classmethod (sync or async).
_REGISTRY: dict[str, type] = {
    "redundancy_rate": RedundancyRateRule,
    "monotonic_progress": MonotonicProgressRule,
    "tool_sequence": ToolSequenceRule,
    "data_dependency": DataDependencyRule,
    "cycle_breaker": CycleBreakRule,
    "token_efficiency": TokenEfficiencyRule,
    "mutation_matcher": MutationMatcherRule,
    "terminal_state": TerminalStateRule,
    "tool_result_type": ToolResultTypeRule,
    "llm_response_format": LlmResponseFormatRule,
    "llm_grounding": LlmGroundingRule,
}


class HardRuleRunner:
    """Orchestrates trajectory-level hard rule generation from a YAML config.

    Reads ``hard_rules_config.yaml`` at construction time.  Dispatches
    ``from_trajectory`` on each enabled rule class, passing the rule-specific
    parameters defined in the YAML.

    Attributes:
        config_path: Path to the YAML configuration file.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or _CONFIG_PATH
        with open(self.config_path) as fh:
            self._config: dict = yaml.safe_load(fh)

    async def run(
        self,
        trajectory: Trajectory,
        embed_client: Optional[AzureFoundryClient] = None,
    ) -> list[HardRule]:
        """Generate all enabled trajectory-level hard rules.

        Args:
            trajectory: The full trajectory to analyse.
            embed_client: Optional Azure Foundry client for Rule b (embedding).
                Rule b is silently skipped when None.

        Returns:
            Ordered list of HardRule instances, one group per enabled rule.
        """
        rules_config: dict = self._config.get("trajectory_rules", {})
        failure_keywords: list[str] = self._config.get("failure_keywords", [])
        all_rules: list[HardRule] = []

        for rule_name, rule_cfg in rules_config.items():
            if not rule_cfg.get("enabled", True):
                continue

            cls = _REGISTRY.get(rule_name)
            if cls is None:
                _log.warning("HardRuleRunner: unknown rule '%s', skipping.", rule_name)
                continue

            # Build kwargs from config, excluding the 'enabled' flag.
            params = {k: v for k, v in rule_cfg.items() if k != "enabled"}

            # Inject special context where needed.
            if rule_name == "monotonic_progress":
                params["embed_client"] = embed_client
            if rule_name == "mutation_matcher" and failure_keywords:
                params["failure_keywords"] = failure_keywords

            try:
                factory = cls.from_trajectory
                if inspect.iscoroutinefunction(factory):
                    instances = await factory(trajectory, **params)
                else:
                    instances = factory(trajectory, **params)
                all_rules.extend(instances)
            except (
                Exception
            ) as exc:  # noqa: BLE001 — one rule failure must not stop others
                _log.error(
                    "HardRuleRunner: rule '%s' raised an error: %s",
                    rule_name,
                    exc,
                    exc_info=True,
                )

        return all_rules
