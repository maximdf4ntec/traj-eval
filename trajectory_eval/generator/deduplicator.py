"""Rule Deduplicator — merges overlapping per-step observations into global invariants.

This module groups raw :class:`~trajectory_eval.models.contract.CompiledRule`
instances by abstract identity (category + kind + target equivalence), detects
inconsistencies, and merges consistent observations into single global
invariants with accumulated support and maximum confidence.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 8.4, 9.4, 12.3
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from trajectory_eval.models.contract import (
    CompiledRule,
    RuleMetadata,
)
from trajectory_eval.models.execution_report import InconsistencyFlag
from trajectory_eval.models.rule import ConfidenceLevel

# Ordering map for ConfidenceLevel comparison (higher value = higher confidence).
_CONFIDENCE_ORDER: dict[ConfidenceLevel, int] = {
    ConfidenceLevel.low: 0,
    ConfidenceLevel.medium: 1,
    ConfidenceLevel.high: 2,
}


def _max_confidence(levels: list[ConfidenceLevel]) -> ConfidenceLevel:
    """Return the highest confidence level from a list.

    Uses an explicit ordering since :class:`ConfidenceLevel` does not
    implement comparison operators.
    """
    return max(levels, key=lambda c: _CONFIDENCE_ORDER[c])


@dataclass
class DeduplicationResult:
    """Result of the deduplication pass.

    Attributes:
        rules: Deduplicated, sequentially re-numbered compiled rules.
        flags: Contradictory patterns that could not be resolved.
    """

    rules: list[CompiledRule] = field(default_factory=list)
    flags: list[InconsistencyFlag] = field(default_factory=list)


class RuleDeduplicator:
    """Merges overlapping per-step observations into global invariants.

    Groups rules by their canonical identity key ``(category, kind,
    target_fingerprint)`` and either merges consistent groups (identical
    constraint dicts) into a single rule with accumulated support, or
    emits an :class:`InconsistencyFlag` when constraints conflict.
    """

    def deduplicate(self, rules: list[CompiledRule]) -> DeduplicationResult:
        """Deduplicate a list of compiled rules.

        Args:
            rules: Raw compiled rules (potentially containing duplicates).

        Returns:
            A :class:`DeduplicationResult` with merged rules and any
            inconsistency flags.
        """
        groups: dict[str, list[CompiledRule]] = defaultdict(list)

        for rule in rules:
            key = self._identity_key(rule)
            groups[key].append(rule)

        deduplicated: list[CompiledRule] = []
        flags: list[InconsistencyFlag] = []
        seq = 0

        for key, group in groups.items():
            constraints = [r.constraint for r in group]

            if self._all_consistent(constraints):
                seq += 1
                support = len(group)
                raw_confidence = _max_confidence([r.metadata.confidence for r in group])
                # Adjust confidence based on support: a single observation
                # cannot justify high confidence regardless of the rule
                # class's default.
                final_confidence = self._adjust_confidence(raw_confidence, support)
                merged = CompiledRule(
                    id=f"rule_{seq:03d}",
                    category=group[0].category,
                    kind=group[0].kind,
                    target=group[0].target,
                    constraint=constraints[0],  # All identical
                    cardinality=group[0].cardinality,
                    metadata=RuleMetadata(
                        confidence=final_confidence,
                        support=support,
                    ),
                )
                deduplicated.append(merged)
            else:
                flags.append(
                    InconsistencyFlag(
                        target_fingerprint=key,
                        category=group[0].category,
                        kind=group[0].kind,
                        conflicting_constraints=constraints,
                        observation_count=len(group),
                    )
                )

        return DeduplicationResult(rules=deduplicated, flags=flags)

    def _identity_key(self, rule: CompiledRule) -> str:
        """Compute a canonical fingerprint for grouping.

        The key is ``"{category}::{kind}::{sorted_target_json}"``, ensuring
        rules that describe the same logical target are grouped together
        regardless of field insertion order.
        """
        target_dict = rule.target.model_dump(exclude_none=True)
        target_json = json.dumps(target_dict, sort_keys=True)
        return f"{rule.category.value}::{rule.kind}::{target_json}"

    def _all_consistent(self, constraints: list[dict]) -> bool:  # type: ignore[type-arg]
        """Check whether all constraint dicts in a group are identical.

        Uses canonical JSON serialization (sorted keys) for comparison so
        that dict ordering differences don't cause false inconsistencies.

        Returns:
            ``True`` if all constraints are identical; ``False`` otherwise.
        """
        if len(constraints) <= 1:
            return True
        canonical = json.dumps(constraints[0], sort_keys=True)
        return all(json.dumps(c, sort_keys=True) == canonical for c in constraints[1:])

    @staticmethod
    def _adjust_confidence(raw: ConfidenceLevel, support: int) -> ConfidenceLevel:
        """Downgrade confidence when support is too low to justify it.

        Policy:
            - support >= 3: keep raw confidence as-is
            - support == 2: cap at medium
            - support == 1: cap at low
        """
        if support >= 3:
            return raw
        if support == 2:
            if raw == ConfidenceLevel.high:
                return ConfidenceLevel.medium
            return raw
        # support == 1
        return ConfidenceLevel.low
