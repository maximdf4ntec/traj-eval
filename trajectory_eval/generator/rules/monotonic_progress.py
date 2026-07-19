"""Rule b — Monotonic Progress (Token-to-Output Ratio via cosine similarity).

For every llm_response step N, the response is compared against the prior
*prior_steps_window* responses.  A cosine similarity >= *stagnation_threshold*
signals that the agent is spending tokens without producing novel output
(stagnation / idling).

Embedding calls are delegated to the AzureFoundryClient.  If the client is
None or the call fails, all Rule-b instances are silently skipped so the
pipeline never crashes.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import StepType, Trajectory
from trajectory_eval.generator.rules._helpers import cosine_similarity

_log = logging.getLogger(__name__)


class MonotonicProgressRule(HardRule):
    """Rule b: a later llm_response must be sufficiently novel relative to prior ones.

    Attributes:
        step_index_compared: The step index of the earlier response being compared.
        stagnation_threshold: Maximum allowed cosine similarity before stagnation fires.
        observed_similarity: Cosine similarity observed between the two responses.
    """

    # Rule-specific typed fields.
    step_index_compared: int
    stagnation_threshold: float
    observed_similarity: float

    # Class-level defaults for base Rule fields.
    polarity: RulePolarity = RulePolarity.neutral
    scope: RuleScope = RuleScope.frame
    step_type: Optional[StepType] = StepType.llm_response
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    # Derived text fields.
    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "MonotonicProgressRule":
        """Compute rule_description and pseudocode from typed fields."""
        self.rule_description = (
            f"Response at step {self.step_index} must be novel relative to "
            f"step {self.step_index_compared} (cosine similarity must be < "
            f"{self.stagnation_threshold}). "
            f"Observed similarity: {self.observed_similarity:.3f}."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the cosine-similarity stagnation-check pseudocode.

        Returns:
            Assertion string comparing observed similarity to the threshold.
        """
        return (
            f"cosine_similarity("
            f"embed(step[{self.step_index}].response), "
            f"embed(step[{self.step_index_compared}].response)"
            f") < {self.stagnation_threshold}"
            f"  # observed: {self.observed_similarity:.3f}"
        )

    @classmethod
    async def from_trajectory(
        cls,
        trajectory: Trajectory,
        embed_client: object | None = None,
        stagnation_threshold: float = 0.95,
        prior_steps_window: int = 2,
    ) -> list["MonotonicProgressRule"]:
        """Build monotonic-progress rules by comparing llm_response embeddings.

        Args:
            trajectory: The full trajectory to analyse.
            embed_client: AzureFoundryClient instance used for embedding.
                Rule b is silently skipped when None.
            stagnation_threshold: Cosine similarity >= this signals stagnation.
            prior_steps_window: Number of preceding llm_response steps to compare.

        Returns:
            One rule per (step-N, step-M) pair evaluated; empty list on skip/error.
        """
        if embed_client is None:
            _log.debug("Rule b: skipped — no embed_client provided.")
            return []

        llm_steps = [
            s for s in trajectory.steps if s.step_type == StepType.llm_response
        ]
        if len(llm_steps) < 2:
            return []

        texts = [s.response or "" for s in llm_steps]
        try:
            embeddings = await embed_client.embed(texts)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            _log.warning("Rule b: embedding call failed, skipping. Cause: %s", exc)
            return []

        rules: list[MonotonicProgressRule] = []
        for i in range(1, len(llm_steps)):
            for j in range(max(0, i - prior_steps_window), i):
                sim = cosine_similarity(embeddings[i], embeddings[j])
                step_n = llm_steps[i]
                step_m = llm_steps[j]
                rules.append(
                    cls(
                        id=f"global_monotonic_{step_n.index}_vs_{step_m.index}",
                        step_index=step_n.index,
                        step_index_compared=step_m.index,
                        stagnation_threshold=stagnation_threshold,
                        observed_similarity=sim,
                    )
                )
        return rules
