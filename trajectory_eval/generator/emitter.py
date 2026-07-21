"""Rule Emitter — converts internal HardRule instances to CompiledRule.

This module implements a registry of emitter functions, each responsible for
converting a specific concrete HardRule subclass into an abstract, step-agnostic
CompiledRule suitable for inclusion in the Behavior Contract.

Each emitter function:
1. Takes a concrete HardRule subclass instance.
2. Returns a CompiledRule with step-agnostic target and constraint.
3. Uses a placeholder ``id`` (actual IDs are assigned by the deduplicator).

The public entry point is :func:`emit`, which dispatches to the correct
emitter based on the rule's type.
"""

from __future__ import annotations

from typing import Callable

from trajectory_eval.generator.rules.data_dependency import DataDependencyRule
from trajectory_eval.generator.rules.llm_format import LlmResponseFormatRule
from trajectory_eval.generator.rules.llm_grounding import LlmGroundingRule
from trajectory_eval.generator.rules.mutation_matcher import MutationMatcherRule
from trajectory_eval.generator.rules.terminal_state import TerminalStateRule
from trajectory_eval.generator.rules.tool_checks import (
    ToolParamCountRule,
    ToolParamTypeRule,
)
from trajectory_eval.generator.rules.tool_result_type import ToolResultTypeRule
from trajectory_eval.generator.rules.tool_sequence import ToolSequenceRule
from trajectory_eval.models.contract import (
    CompiledRule,
    RuleCardinality,
    RuleCategory,
    RuleMetadata,
    RuleTarget,
)
from trajectory_eval.models.rule import ConfidenceLevel, HardRule

# ---------------------------------------------------------------------------
# Type alias for emitter functions.
# ---------------------------------------------------------------------------

EmitterFn = Callable[[HardRule], CompiledRule]

# ---------------------------------------------------------------------------
# Placeholder ID used by all emitters. The deduplicator assigns final IDs.
# ---------------------------------------------------------------------------

_PLACEHOLDER_ID = "rule_000"


# ---------------------------------------------------------------------------
# Individual emitter functions.
# ---------------------------------------------------------------------------


def emit_data_dependency(rule: HardRule) -> CompiledRule:
    """Convert a DataDependencyRule to a step-agnostic CompiledRule.

    Produces a ``provenance`` / ``data_lineage`` rule expressing that a
    consuming tool's parameter must originate from a specific source tool's
    output.

    The source_tool is included in the target (via the ``tool_pair`` field)
    so that rules with different source tools are treated as distinct
    invariants during deduplication. Without this, a tool that receives data
    from multiple sources would produce "conflicting" constraints and be
    flagged as an inconsistency instead of being kept as separate rules.
    """
    assert isinstance(rule, DataDependencyRule)

    source = rule.source_tool_name or rule.tool_name

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.provenance,
        kind="data_lineage",
        target=RuleTarget(
            tool=rule.tool_name,
            parameter=rule.param_key,
            tool_pair=(source, rule.tool_name),
        ),
        constraint={
            "must_originate_from": {
                "tool": source,
                "output_field": rule.param_key,
            }
        },
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_tool_sequence(rule: HardRule) -> CompiledRule:
    """Convert a ToolSequenceRule to a step-agnostic CompiledRule.

    Produces a ``workflow`` / ``tool_ordering`` rule expressing that tool_b
    is valid (or blocked) after tool_a succeeds (or fails).
    """
    assert isinstance(rule, ToolSequenceRule)

    from trajectory_eval.models.rule import RulePolarity

    condition = "a_succeeds" if rule.polarity == RulePolarity.positive else "a_fails"
    behavior = "b_valid" if rule.polarity == RulePolarity.positive else "b_blocked"

    # Include condition in the kind to differentiate positive/negative variants
    # so deduplication doesn't treat them as conflicting.
    kind = f"tool_ordering_{condition}"

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.workflow,
        kind=kind,
        target=RuleTarget(tool_pair=(rule.tool_a_name, rule.tool_b_name)),
        constraint={"condition": condition, "behavior": behavior},
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_param_type(rule: HardRule) -> CompiledRule:
    """Convert a ToolParamTypeRule to a step-agnostic CompiledRule.

    Produces an ``interface`` / ``param_type`` rule asserting that a specific
    parameter of a tool must have the expected Python type.
    """
    assert isinstance(rule, ToolParamTypeRule)

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.interface,
        kind="param_type",
        target=RuleTarget(tool=rule.tool_name, parameter=rule.param_key),
        constraint={"expected_type": rule.expected_type},
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_param_count(rule: HardRule) -> CompiledRule:
    """Convert a ToolParamCountRule to a step-agnostic CompiledRule.

    Produces an ``interface`` / ``param_count`` rule asserting that a tool
    must receive exactly N parameters.
    """
    assert isinstance(rule, ToolParamCountRule)

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.interface,
        kind="param_count",
        target=RuleTarget(tool=rule.tool_name),
        constraint={"expected_count": rule.expected_count},
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_result_type(rule: HardRule) -> CompiledRule:
    """Convert a ToolResultTypeRule to a step-agnostic CompiledRule.

    Produces an ``interface`` / ``result_format`` rule asserting that a
    tool's output must be valid for its detected structured type.
    """
    assert isinstance(rule, ToolResultTypeRule)

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.interface,
        kind="result_format",
        target=RuleTarget(tool=rule.tool_name),
        constraint={"expected_format": rule.detected_type.value},
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_llm_format(rule: HardRule) -> CompiledRule:
    """Convert a LlmResponseFormatRule to a step-agnostic CompiledRule.

    Produces an ``interface`` / ``response_format`` rule asserting that
    the assistant response must conform to a requested format.
    """
    assert isinstance(rule, LlmResponseFormatRule)

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.interface,
        kind="response_format",
        target=RuleTarget(response="assistant"),
        constraint={"expected_format": rule.requested_format},
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_llm_grounding(rule: HardRule) -> CompiledRule:
    """Convert a LlmGroundingRule to a step-agnostic CompiledRule.

    Produces a ``grounding`` / ``entity_reference`` rule asserting that an
    entity referenced in the LLM response must appear in prior tool outputs.
    """
    assert isinstance(rule, LlmGroundingRule)

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.grounding,
        kind="entity_reference",
        target=RuleTarget(entity=rule.entity_value),
        constraint={
            "entity_type": rule.entity_type,
            "must_appear_in_prior_tool_outputs": True,
            "context_window": rule.context_window,
        },
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_terminal_state(rule: HardRule) -> CompiledRule:
    """Convert a TerminalStateRule to a step-agnostic CompiledRule.

    Produces a ``termination`` / ``completion_signal`` rule with
    trajectory-wide scope and ``single`` cardinality (applies to exactly
    one point — the end of the trajectory).
    """
    assert isinstance(rule, TerminalStateRule)

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.termination,
        kind="completion_signal",
        target=RuleTarget(scope="trajectory"),
        constraint={
            "found_keyword": rule.found_keyword or None,
            "terminal_condition": "last_step_contains_keyword",
        },
        cardinality=RuleCardinality.single,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


def emit_mutation_matcher(rule: HardRule) -> CompiledRule:
    """Convert a MutationMatcherRule to a step-agnostic CompiledRule.

    Produces an ``adaptation`` / ``failure_recovery`` rule asserting that
    the agent must adapt its approach after a tool failure.
    """
    assert isinstance(rule, MutationMatcherRule)

    return CompiledRule(
        id=_PLACEHOLDER_ID,
        category=RuleCategory.adaptation,
        kind="failure_recovery",
        target=RuleTarget(tool=rule.failed_tool_name or "unknown"),
        constraint={
            "on_failure": "agent_must_adapt",
            "adaptation_required": True,
        },
        cardinality=RuleCardinality.all,
        metadata=RuleMetadata(confidence=rule.confidence, support=1),
    )


# ---------------------------------------------------------------------------
# Emitter registry — maps rule classes to their emitter functions.
# ---------------------------------------------------------------------------

_EMITTER_REGISTRY: dict[type, EmitterFn] = {
    DataDependencyRule: emit_data_dependency,
    ToolSequenceRule: emit_tool_sequence,
    ToolParamTypeRule: emit_param_type,
    ToolParamCountRule: emit_param_count,
    ToolResultTypeRule: emit_result_type,
    LlmResponseFormatRule: emit_llm_format,
    LlmGroundingRule: emit_llm_grounding,
    TerminalStateRule: emit_terminal_state,
    MutationMatcherRule: emit_mutation_matcher,
}


# ---------------------------------------------------------------------------
# Public dispatch function.
# ---------------------------------------------------------------------------


def emit(rule: HardRule) -> CompiledRule:
    """Convert an internal HardRule instance to an abstract CompiledRule.

    Dispatches to the registered emitter function based on the rule's type.
    Raises ValueError if no emitter is registered for the given rule class.

    Args:
        rule: A concrete HardRule subclass instance.

    Returns:
        A CompiledRule with step-agnostic target, constraint, and metadata.

    Raises:
        ValueError: When no emitter is registered for the rule's type.
    """
    emitter = _EMITTER_REGISTRY.get(type(rule))
    if emitter is None:
        raise ValueError(f"No emitter registered for {type(rule).__name__}")
    return emitter(rule)
