"""Rule c — Tool Sequence Dependency.

For every tool_result step R that bridges a preceding call A and a following
call B, ToolSequenceRule instances are emitted with confidence scoring based
on three signals:

1. Data-flow: B uses a parameter originating from A's output → high confidence
2. Powerful couple: (A, B) in configurable registry → high confidence
3. Count threshold: occurrences >= threshold → high confidence

Pairs below threshold without structural evidence are suppressed (not emitted).
Pairs with inconsistent ordering are skipped (routed to flags).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from pydantic import model_validator

from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import StepType, Trajectory
from trajectory_eval.generator.rules._helpers import (
    failed_step_indices,
    next_tool_call,
    preceding_tool_call,
)


# ---------------------------------------------------------------------------
# Internal observation type for pair collection
# ---------------------------------------------------------------------------


@dataclass
class _PairObservation:
    """A single observation of an A→B tool pair via a bridging tool_result."""

    tool_a_step: int
    result_step: int
    tool_b_step: int
    a_succeeded: bool


# ---------------------------------------------------------------------------
# Confidence heuristic
# ---------------------------------------------------------------------------


def _compute_confidence(
    tool_a: str,
    tool_b: str,
    occurrences: int,
    has_data_flow: bool,
    powerful_couples: set[tuple[str, str]],
    threshold: int = 3,
) -> Optional[ConfidenceLevel]:
    """Return confidence level or None (suppress the rule).

    Signals (any one = high confidence):
    1. Data-flow: B uses a param originating from A's output → high
    2. Powerful couple: (A, B) in registry → high
    3. Count threshold: occurrences >= threshold → high

    If none of the above: return None (do not emit rule).

    Args:
        tool_a: Name of the prerequisite tool.
        tool_b: Name of the dependent tool.
        occurrences: Number of times A→B was observed with A succeeding.
        has_data_flow: Whether B uses a parameter originating from A's output.
        powerful_couples: Set of (tool_a, tool_b) pairs considered
            complementary (read/write, create/delete, etc.).
        threshold: Minimum observation count for count-based confidence.

    Returns:
        ConfidenceLevel.high if any signal fires, or None to suppress.
    """
    if has_data_flow:
        return ConfidenceLevel.high
    if (tool_a, tool_b) in powerful_couples:
        return ConfidenceLevel.high
    if occurrences >= threshold:
        return ConfidenceLevel.high
    return None


# ---------------------------------------------------------------------------
# Data-flow cross-reference
# ---------------------------------------------------------------------------


def _check_data_dependency_with_steps(
    tool_a: str,
    tool_b: str,
    data_dependency_rules: list,
    step_tool_map: dict[int, str],
) -> bool:
    """Check data-flow link using step-to-tool mapping for source resolution.

    Args:
        tool_a: Source tool name.
        tool_b: Consuming tool name.
        data_dependency_rules: List of DataDependencyRule instances.
        step_tool_map: Mapping from step index to tool name for tool_call steps.

    Returns:
        True if tool_b uses a parameter that originates from tool_a's output.
    """
    from trajectory_eval.generator.rules.data_dependency import DataDependencyRule

    for rule in data_dependency_rules:
        if not isinstance(rule, DataDependencyRule):
            continue
        if rule.tool_name != tool_b:
            continue
        # Resolve source_step to a tool name.
        # source_step is a tool_result step; the preceding tool_call is tool_a.
        # In practice, a tool_result at step N typically follows a tool_call
        # at step N-1. We check adjacent tool_call steps.
        source_step_idx = rule.source_step
        # The tool_result's preceding tool_call is the source tool.
        # Check step_tool_map for the tool_call immediately before source_step.
        for candidate_idx in range(source_step_idx, -1, -1):
            if candidate_idx in step_tool_map:
                if step_tool_map[candidate_idx] == tool_a:
                    return True
                break

    return False


# ---------------------------------------------------------------------------
# Inconsistency detection
# ---------------------------------------------------------------------------


def _is_inconsistent(observations: list[_PairObservation]) -> bool:
    """Detect inconsistent ordering in pair observations.

    A pair is inconsistent when A sometimes succeeds and B follows, but
    other times A succeeds and B does NOT follow (i.e., a different tool
    follows instead). We detect this by checking if the success rate is
    significantly below 100% — meaning the pattern is not reliable.

    For simplicity: if fewer than half the observations show A succeeding,
    the pattern is considered inconsistent (unreliable signal).

    Args:
        observations: All observations of this A→B pair.

    Returns:
        True if the ordering pattern is unreliable/inconsistent.
    """
    if not observations:
        return True
    success_count = sum(1 for o in observations if o.a_succeeded)
    total = len(observations)
    # If A never succeeds in the observations, the positive pattern is
    # unsupported — treat as inconsistent.
    if success_count == 0:
        return True
    # If fewer than half have A succeeding, the pair is inconsistent.
    return success_count < (total / 2)


# ---------------------------------------------------------------------------
# ToolSequenceRule
# ---------------------------------------------------------------------------


class ToolSequenceRule(HardRule):
    """Rule c: tool B may only follow tool A given A's result status.

    One instance is created per polarity per A-result-B triple found in the
    trajectory.  The ``polarity`` field distinguishes the positive (enforce
    ordering from a successful run) from the negative (block B when A failed)
    variant.

    Attributes:
        tool_a_name: Name of tool A (the prerequisite call).
        tool_a_step: Step index of tool A.
        tool_b_name: Name of tool B (the dependent call).
        result_step: Step index of the tool_result between A and B.
    """

    # Rule-specific typed fields.
    tool_a_name: str
    tool_a_step: int
    tool_b_name: str
    result_step: int

    # Class-level defaults for base Rule fields (polarity is NOT defaulted —
    # it must be supplied at construction time to distinguish variants).
    scope: RuleScope = RuleScope.frame
    step_type: Optional[StepType] = StepType.tool_call
    confidence: ConfidenceLevel = ConfidenceLevel.medium

    # Derived text fields.
    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "ToolSequenceRule":
        """Compute rule_description and pseudocode based on polarity."""
        if self.polarity == RulePolarity.positive:
            self.rule_description = (
                f"Tool '{self.tool_b_name}' at step {self.step_index} may only be "
                f"called after '{self.tool_a_name}' (step {self.tool_a_step}) has "
                f"been successfully executed."
            )
        else:
            self.rule_description = (
                f"Tool '{self.tool_b_name}' at step {self.step_index} must NOT be "
                f"called when '{self.tool_a_name}' (step {self.tool_a_step}) failed "
                f"(tool_status != 'success')."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        """Return the sequence-dependency assertion pseudocode.

        Returns:
            Assertion string for the positive or negative variant.
        """
        if self.polarity == RulePolarity.positive:
            return (
                f"step[{self.result_step}].tool_status == 'success'"
                f" => step[{self.step_index}].tool_name == '{self.tool_b_name}'"
                f" is valid"
            )
        return (
            f"step[{self.result_step}].tool_status != 'success'"
            f" => step[{self.step_index}].tool_name != '{self.tool_b_name}'"
        )

    @classmethod
    def from_trajectory(
        cls,
        trajectory: Trajectory,
        *,
        powerful_couples: Optional[set[tuple[str, str]] | list] = None,
        confidence_threshold: int = 3,
        data_dependency_rules: Optional[list] = None,
    ) -> list["ToolSequenceRule"]:
        """Build sequence rules with confidence-based filtering.

        Collects all A→B pairs from the trajectory, applies multi-signal
        confidence scoring, and only emits rules that meet at least one
        qualifying signal (data-flow, powerful couple, or count threshold).

        Args:
            trajectory: The full trajectory to analyse.
            powerful_couples: Set of (tool_a, tool_b) pairs considered
                complementary. Loaded from YAML config (accepts list of
                2-element lists or set of tuples). Defaults to empty set.
            confidence_threshold: Minimum observation count for count-based
                confidence. Defaults to 3.
            data_dependency_rules: Pre-computed DataDependencyRule instances
                for cross-referencing data flow. Defaults to empty list.

        Returns:
            ToolSequenceRule instances (positive + negative) for pairs that
            pass the confidence heuristic. Pairs below threshold or with
            inconsistent ordering are suppressed.
        """
        # Normalize powerful_couples from YAML list-of-lists to set-of-tuples
        if powerful_couples is None:
            couples_set: set[tuple[str, str]] = set()
        elif isinstance(powerful_couples, set):
            couples_set = powerful_couples
        else:
            # YAML produces list of lists; convert to set of tuples
            couples_set = {
                (pair[0], pair[1]) for pair in powerful_couples if len(pair) == 2
            }

        if data_dependency_rules is None:
            data_dependency_rules = []

        steps = trajectory.steps

        # Build step-index → tool-name map for data-flow resolution
        step_tool_map: dict[int, str] = {}
        for step in steps:
            if step.step_type == StepType.tool_call:
                step_tool_map[step.index] = step.tool_name or ""

        # Phase 1: Collect all A→B pairs
        pairs: dict[tuple[str, str], list[_PairObservation]] = defaultdict(list)

        # Identify tool_result steps that are structurally failed (followed
        # by a StepType.error step).
        structurally_failed = failed_step_indices(steps)

        for result in steps:
            if result.step_type != StepType.tool_result:
                continue
            a_call = preceding_tool_call(steps, result.index)
            b_call = next_tool_call(steps, result.index)
            if a_call is None or b_call is None:
                continue

            tool_a = a_call.tool_name or ""
            tool_b = b_call.tool_name or ""

            # A tool_result is only classified as a failure when there is
            # structural evidence: an adjacent StepType.error step.  Naive
            # keyword matching (e.g. "error" in output) produces false
            # positives when outputs incidentally contain those words in
            # file paths, source code, or documentation text.
            a_succeeded = result.index not in structurally_failed

            pairs[(tool_a, tool_b)].append(
                _PairObservation(
                    tool_a_step=a_call.index,
                    result_step=result.index,
                    tool_b_step=b_call.index,
                    a_succeeded=a_succeeded,
                )
            )

        # Phase 2: Score and filter
        rules: list[ToolSequenceRule] = []

        for (tool_a, tool_b), observations in pairs.items():
            # Skip self-loops — a tool following itself is not a meaningful
            # ordering constraint.
            if tool_a == tool_b:
                continue

            # Count consistent occurrences (A succeeds → B follows)
            success_count = sum(1 for o in observations if o.a_succeeded)

            # Check for inconsistency — skip if unreliable
            if _is_inconsistent(observations):
                continue

            # Signal 1: Data-flow dependency
            has_data_flow = _check_data_dependency_with_steps(
                tool_a, tool_b, data_dependency_rules, step_tool_map
            )

            # Signal 2 & 3: Powerful couple and count threshold
            confidence = _compute_confidence(
                tool_a=tool_a,
                tool_b=tool_b,
                occurrences=success_count,
                has_data_flow=has_data_flow,
                powerful_couples=couples_set,
                threshold=confidence_threshold,
            )

            # If confidence is None, suppress (don't emit rule)
            if confidence is None:
                continue

            # Suppress count-only rules when data-flow exists in the REVERSE
            # direction. This means (B→A) is the real dependency and (A→B) is
            # just the return arc (e.g., after running python, user goes back
            # to edit — not a real ordering constraint).
            if not has_data_flow and (tool_a, tool_b) not in couples_set:
                reverse_has_data_flow = _check_data_dependency_with_steps(
                    tool_b, tool_a, data_dependency_rules, step_tool_map
                )
                if reverse_has_data_flow:
                    continue

            # Emit rules for the first observation's step indices
            # (representative instance; deduplication merges later)
            first_obs = observations[0]
            shared = dict(
                tool_a_name=tool_a,
                tool_a_step=first_obs.tool_a_step,
                tool_b_name=tool_b,
                result_step=first_obs.result_step,
                step_index=first_obs.tool_b_step,
            )

            # Only emit rules for patterns actually observed.
            # Positive: A succeeded → B followed (observed in success_count).
            # Negative: A failed → B did NOT follow (only if observed).
            if success_count > 0:
                rules.append(
                    cls(
                        id=f"tool_seq_pos_{first_obs.tool_b_step}",
                        polarity=RulePolarity.positive,
                        confidence=confidence,
                        **shared,
                    )
                )

            # Count failure observations where A failed and B still followed
            # (potential violation). Only emit negative rule if failures were
            # actually observed in the trajectory.
            failure_count = sum(1 for o in observations if not o.a_succeeded)
            if failure_count > 0:
                rules.append(
                    cls(
                        id=f"tool_seq_neg_{first_obs.tool_b_step}",
                        polarity=RulePolarity.negative,
                        confidence=confidence,
                        **shared,
                    )
                )

        return rules
