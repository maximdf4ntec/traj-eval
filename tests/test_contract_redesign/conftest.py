"""Shared Hypothesis strategies for contract-redesign property tests.

Provides reusable strategies for generating:
- CompiledRule instances (structural completeness testing)
- Identical rule groups (deduplication testing)
- Trajectory instances (end-to-end testing)
- Concrete HardRule instances (emitter testing)

**Validates: Requirements 1.3, 6.1**
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import strategies as st
from hypothesis.strategies import composite

from trajectory_eval.models.contract import (
    CompiledRule,
    RuleCardinality,
    RuleCategory,
    RuleMetadata,
    RuleTarget,
)
from trajectory_eval.models.rule import ConfidenceLevel, RulePolarity, RuleScope
from trajectory_eval.models.trajectory import Step, StepType, Trajectory


# ---------------------------------------------------------------------------
# Realistic value pools
# ---------------------------------------------------------------------------

_TOOL_NAMES = [
    "read_file",
    "write_file",
    "str_replace",
    "execute_command",
    "list_directory",
    "create_file",
    "search_files",
    "run_tests",
    "git_diff",
    "submit_patch",
]

_PARAM_NAMES = [
    "path",
    "content",
    "old_str",
    "new_str",
    "command",
    "query",
    "file_path",
    "directory",
    "pattern",
    "timeout",
]

_ENTITY_VALUES = [
    "src/main.py",
    "tests/test_utils.py",
    "#123",
    "#456",
    "abc1234",
    "deadbeef",
    "config/settings.yaml",
]

# Mapping from category to realistic kinds
_KINDS_BY_CATEGORY: dict[RuleCategory, list[str]] = {
    RuleCategory.provenance: ["data_lineage"],
    RuleCategory.workflow: ["tool_ordering"],
    RuleCategory.interface: [
        "param_type",
        "param_count",
        "result_format",
        "response_format",
    ],
    RuleCategory.adaptation: ["failure_recovery"],
    RuleCategory.grounding: ["entity_reference"],
    RuleCategory.termination: ["completion_signal"],
}


# ---------------------------------------------------------------------------
# Strategy: compiled_rules
# ---------------------------------------------------------------------------


@composite
def compiled_rules(draw: st.DrawFn) -> CompiledRule:
    """Generate a valid CompiledRule with all required fields populated.

    Produces rules with:
    - id: formatted as rule_NNN
    - category: drawn from RuleCategory enum
    - kind: realistic kind per category
    - target: valid RuleTarget with appropriate fields
    - constraint: category/kind-appropriate constraint dict
    - cardinality: drawn from RuleCardinality
    - metadata: valid RuleMetadata with confidence from ConfidenceLevel, support >= 1
    """
    rule_num = draw(st.integers(min_value=1, max_value=999))
    rule_id = f"rule_{rule_num:03d}"

    category = draw(st.sampled_from(list(RuleCategory)))
    kind = draw(st.sampled_from(_KINDS_BY_CATEGORY[category]))
    target = draw(_target_for_category(category, kind))
    constraint = draw(_constraint_for_kind(kind))
    cardinality = draw(st.sampled_from(list(RuleCardinality)))
    confidence = draw(st.sampled_from(list(ConfidenceLevel)))
    support = draw(st.integers(min_value=1, max_value=50))

    return CompiledRule(
        id=rule_id,
        category=category,
        kind=kind,
        target=target,
        constraint=constraint,
        cardinality=cardinality,
        metadata=RuleMetadata(confidence=confidence, support=support),
    )


@composite
def _target_for_category(
    draw: st.DrawFn, category: RuleCategory, kind: str
) -> RuleTarget:
    """Generate a RuleTarget appropriate for the given category/kind."""
    tool = draw(st.sampled_from(_TOOL_NAMES))

    if category == RuleCategory.provenance:
        param = draw(st.sampled_from(_PARAM_NAMES))
        return RuleTarget(tool=tool, parameter=param)

    if category == RuleCategory.workflow:
        tool_b = draw(st.sampled_from(_TOOL_NAMES))
        return RuleTarget(tool_pair=(tool, tool_b))

    if category == RuleCategory.interface:
        if kind in ("param_type", "param_count"):
            param = draw(st.sampled_from(_PARAM_NAMES))
            return RuleTarget(tool=tool, parameter=param)
        if kind == "result_format":
            return RuleTarget(tool=tool)
        # response_format
        return RuleTarget(response="assistant")

    if category == RuleCategory.adaptation:
        return RuleTarget(tool=tool)

    if category == RuleCategory.grounding:
        entity = draw(st.sampled_from(_ENTITY_VALUES))
        return RuleTarget(entity=entity)

    # termination
    return RuleTarget(scope="trajectory")


@composite
def _constraint_for_kind(draw: st.DrawFn, kind: str) -> dict:
    """Generate a constraint dict appropriate for the given kind."""
    if kind == "data_lineage":
        source_tool = draw(st.sampled_from(_TOOL_NAMES))
        output_field = draw(st.sampled_from(_PARAM_NAMES))
        return {
            "must_originate_from": {"tool": source_tool, "output_field": output_field}
        }

    if kind == "tool_ordering":
        condition = draw(st.sampled_from(["a_succeeds", "a_fails"]))
        behavior = draw(st.sampled_from(["b_valid", "b_blocked"]))
        return {"condition": condition, "behavior": behavior}

    if kind == "param_type":
        expected_type = draw(
            st.sampled_from(["str", "int", "float", "bool", "list", "dict"])
        )
        return {"expected_type": expected_type}

    if kind == "param_count":
        count = draw(st.integers(min_value=1, max_value=10))
        return {"expected_count": count}

    if kind == "result_format":
        fmt = draw(st.sampled_from(["json", "xml", "python", "number"]))
        return {"expected_format": fmt}

    if kind == "response_format":
        fmt = draw(st.sampled_from(["json", "yaml", "xml"]))
        return {"expected_format": fmt}

    if kind == "failure_recovery":
        return {"on_failure": "agent_must_adapt", "adaptation_required": True}

    if kind == "entity_reference":
        entity_type = draw(st.sampled_from(["file_path", "hash_id", "commit_sha"]))
        window = draw(st.integers(min_value=1, max_value=20))
        return {
            "entity_type": entity_type,
            "must_appear_in_prior_tool_outputs": True,
            "context_window": window,
        }

    # completion_signal (termination)
    keywords = draw(
        st.lists(
            st.sampled_from(["done", "complete", "finished", "resolved", "success"]),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    return {
        "completion_keywords": keywords,
        "terminal_condition": "last_step_contains_keyword",
    }


# ---------------------------------------------------------------------------
# Strategy: identical_rule_group
# ---------------------------------------------------------------------------


@composite
def identical_rule_group(draw: st.DrawFn, n: int = 3) -> list[CompiledRule]:
    """Generate N CompiledRules sharing the same identity key and constraint.

    All rules in the group have the same (category, kind, target) and
    identical constraint dicts — suitable for testing deduplication merging.
    They may differ in id, confidence, and support.

    Args:
        n: Number of rules to generate in the group (default 3).
    """
    # Draw the shared identity
    category = draw(st.sampled_from(list(RuleCategory)))
    kind = draw(st.sampled_from(_KINDS_BY_CATEGORY[category]))
    target = draw(_target_for_category(category, kind))
    constraint = draw(_constraint_for_kind(kind))
    cardinality = draw(st.sampled_from(list(RuleCardinality)))

    rules: list[CompiledRule] = []
    for i in range(n):
        confidence = draw(st.sampled_from(list(ConfidenceLevel)))
        support = draw(st.integers(min_value=1, max_value=10))
        rules.append(
            CompiledRule(
                id=f"rule_{i + 1:03d}",
                category=category,
                kind=kind,
                target=target,
                constraint=constraint,
                cardinality=cardinality,
                metadata=RuleMetadata(confidence=confidence, support=support),
            )
        )

    return rules


# ---------------------------------------------------------------------------
# Strategy: trajectory
# ---------------------------------------------------------------------------

_FIXED_TIMESTAMP = datetime(2024, 1, 1, tzinfo=timezone.utc)


@composite
def trajectory(draw: st.DrawFn, min_steps: int = 3, max_steps: int = 15) -> Trajectory:
    """Generate a realistic Trajectory instance with mixed step types.

    Produces trajectories with:
    - Steps of mixed types (tool_call, tool_result, llm_response)
    - tool_call steps have tool_name and tool_input dict
    - tool_result steps have tool_output
    - Steps have sequential indices
    """
    num_steps = draw(st.integers(min_value=min_steps, max_value=max_steps))
    steps: list[Step] = []

    for i in range(num_steps):
        step_type = draw(
            st.sampled_from(
                [StepType.tool_call, StepType.tool_result, StepType.llm_response]
            )
        )
        step = draw(_step_for_type(i, step_type))
        steps.append(step)

    traj_id = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=4, max_size=12
        )
    )

    return Trajectory(
        id=traj_id,
        source_platform="test",
        steps=steps,
    )


@composite
def _step_for_type(draw: st.DrawFn, index: int, step_type: StepType) -> Step:
    """Generate a Step of the given type with appropriate fields populated."""
    base = {
        "index": index,
        "step_type": step_type,
        "timestamp": _FIXED_TIMESTAMP,
    }

    if step_type == StepType.tool_call:
        tool_name = draw(st.sampled_from(_TOOL_NAMES))
        # Generate a realistic tool_input dict with 1-4 params
        num_params = draw(st.integers(min_value=1, max_value=4))
        params = draw(
            st.fixed_dictionaries(
                {},
                optional={
                    k: st.text(min_size=1, max_size=30)
                    for k in _PARAM_NAMES[:num_params]
                },
            )
        )
        # Ensure at least one param
        if not params:
            params = {_PARAM_NAMES[0]: draw(st.text(min_size=1, max_size=30))}
        return Step(tool_name=tool_name, tool_input=params, **base)

    if step_type == StepType.tool_result:
        output = draw(st.text(min_size=1, max_size=200))
        return Step(tool_output=output, **base)

    # llm_response
    response = draw(st.text(min_size=5, max_size=300))
    return Step(response=response, **base)


# ---------------------------------------------------------------------------
# Strategy: hard_rule — concrete HardRule instances for emitter testing
# ---------------------------------------------------------------------------


@composite
def data_dependency_rules(draw: st.DrawFn) -> "DataDependencyRule":
    """Generate a valid DataDependencyRule instance."""
    from trajectory_eval.generator.rules.data_dependency import DataDependencyRule

    step_idx = draw(st.integers(min_value=1, max_value=50))
    source_step = draw(st.integers(min_value=0, max_value=step_idx - 1))
    tool_name = draw(st.sampled_from(_TOOL_NAMES))
    param_key = draw(st.sampled_from(_PARAM_NAMES))
    param_value = draw(st.text(min_size=1, max_size=50))
    confidence = draw(st.sampled_from(list(ConfidenceLevel)))

    return DataDependencyRule(
        id=f"data_dep_{step_idx}_{param_key}_{source_step}",
        step_index=step_idx,
        param_key=param_key,
        param_value=param_value,
        source_step=source_step,
        tool_name=tool_name,
        confidence=confidence,
    )


@composite
def tool_sequence_rules(draw: st.DrawFn) -> "ToolSequenceRule":
    """Generate a valid ToolSequenceRule instance."""
    from trajectory_eval.generator.rules.tool_sequence import ToolSequenceRule

    tool_a = draw(st.sampled_from(_TOOL_NAMES))
    tool_b = draw(st.sampled_from(_TOOL_NAMES))
    tool_a_step = draw(st.integers(min_value=0, max_value=20))
    result_step = tool_a_step + 1
    step_index = result_step + 1
    polarity = draw(st.sampled_from([RulePolarity.positive, RulePolarity.negative]))
    confidence = draw(st.sampled_from(list(ConfidenceLevel)))

    return ToolSequenceRule(
        id=f"tool_seq_{step_index}",
        step_index=step_index,
        tool_a_name=tool_a,
        tool_a_step=tool_a_step,
        tool_b_name=tool_b,
        result_step=result_step,
        polarity=polarity,
        confidence=confidence,
    )


@composite
def tool_param_type_rules(draw: st.DrawFn) -> "ToolParamTypeRule":
    """Generate a valid ToolParamTypeRule instance."""
    from trajectory_eval.generator.rules.tool_checks import ToolParamTypeRule

    step_idx = draw(st.integers(min_value=0, max_value=50))
    tool_name = draw(st.sampled_from(_TOOL_NAMES))
    param_key = draw(st.sampled_from(_PARAM_NAMES))
    expected_type = draw(
        st.sampled_from(["str", "int", "float", "bool", "list", "dict"])
    )

    return ToolParamTypeRule(
        id=f"tool_params_{step_idx}_{param_key}_type",
        step_index=step_idx,
        tool_name=tool_name,
        param_key=param_key,
        expected_type=expected_type,
    )


@composite
def tool_param_count_rules(draw: st.DrawFn) -> "ToolParamCountRule":
    """Generate a valid ToolParamCountRule instance."""
    from trajectory_eval.generator.rules.tool_checks import ToolParamCountRule

    step_idx = draw(st.integers(min_value=0, max_value=50))
    tool_name = draw(st.sampled_from(_TOOL_NAMES))
    expected_count = draw(st.integers(min_value=1, max_value=10))

    return ToolParamCountRule(
        id=f"tool_params_{step_idx}_count",
        step_index=step_idx,
        tool_name=tool_name,
        expected_count=expected_count,
    )


@composite
def tool_result_type_rules(draw: st.DrawFn) -> "ToolResultTypeRule":
    """Generate a valid ToolResultTypeRule instance."""
    from trajectory_eval.generator.rules.tool_result_type import (
        OutputType,
        ToolResultTypeRule,
    )

    step_idx = draw(st.integers(min_value=0, max_value=50))
    tool_name = draw(st.sampled_from(_TOOL_NAMES))
    detected_type = draw(st.sampled_from(list(OutputType)))
    detection_method = draw(st.sampled_from(["tool_name_hint", "content_detection"]))

    return ToolResultTypeRule(
        id=f"tool_result_type_{step_idx}",
        step_index=step_idx,
        tool_name=tool_name,
        detected_type=detected_type,
        detection_method=detection_method,
        is_valid=True,
        polarity=RulePolarity.positive,
    )


@composite
def llm_format_rules(draw: st.DrawFn) -> "LlmResponseFormatRule":
    """Generate a valid LlmResponseFormatRule instance."""
    from trajectory_eval.generator.rules.llm_format import LlmResponseFormatRule

    step_idx = draw(st.integers(min_value=1, max_value=50))
    prompt_step = draw(st.integers(min_value=0, max_value=step_idx - 1))
    requested_format = draw(st.sampled_from(["json", "yaml", "xml"]))

    return LlmResponseFormatRule(
        id=f"llm_format_{step_idx}_{requested_format}",
        step_index=step_idx,
        requested_format=requested_format,
        prompt_step_index=prompt_step,
        is_valid=True,
        polarity=RulePolarity.positive,
    )


@composite
def llm_grounding_rules(draw: st.DrawFn) -> "LlmGroundingRule":
    """Generate a valid LlmGroundingRule instance."""
    from trajectory_eval.generator.rules.llm_grounding import LlmGroundingRule

    step_idx = draw(st.integers(min_value=1, max_value=50))
    entity_type = draw(st.sampled_from(["file_path", "hash_id", "commit_sha"]))
    entity_value = draw(st.sampled_from(_ENTITY_VALUES))
    context_window = draw(st.integers(min_value=1, max_value=20))

    return LlmGroundingRule(
        id=f"llm_grounding_{step_idx}_{entity_type}",
        step_index=step_idx,
        entity_type=entity_type,
        entity_value=entity_value,
        context_window=context_window,
    )


@composite
def terminal_state_rules(draw: st.DrawFn) -> "TerminalStateRule":
    """Generate a valid TerminalStateRule instance."""
    from trajectory_eval.generator.rules.terminal_state import TerminalStateRule

    step_idx = draw(st.integers(min_value=0, max_value=50))
    last_step_type = draw(
        st.sampled_from(
            [StepType.llm_response, StepType.tool_result, StepType.tool_call]
        )
    )
    keywords = draw(
        st.lists(
            st.sampled_from(["done", "complete", "finished", "resolved", "success"]),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    found_keyword = draw(st.sampled_from(["done", "complete", ""]))

    return TerminalStateRule(
        id=f"terminal_state_{step_idx}",
        step_index=step_idx,
        last_step_index=step_idx,
        last_step_type=last_step_type,
        completion_keywords=keywords,
        found_keyword=found_keyword,
        polarity=RulePolarity.positive,
    )


@composite
def mutation_matcher_rules(draw: st.DrawFn) -> "MutationMatcherRule":
    """Generate a valid MutationMatcherRule instance."""
    from trajectory_eval.generator.rules.mutation_matcher import MutationMatcherRule

    failed_call_step = draw(st.integers(min_value=0, max_value=20))
    failure_step = failed_call_step + 1
    step_idx = failure_step + 1
    adapted = draw(st.booleans())

    return MutationMatcherRule(
        id=f"mutation_{step_idx}",
        step_index=step_idx,
        failure_step=failure_step,
        failed_call_step=failed_call_step,
        adapted=adapted,
    )


@composite
def hard_rules(draw: st.DrawFn):
    """Generate any concrete HardRule instance for emitter testing.

    Draws uniformly from all contract-eligible rule types.
    """
    strategy = draw(
        st.sampled_from(
            [
                data_dependency_rules(),
                tool_sequence_rules(),
                tool_param_type_rules(),
                tool_param_count_rules(),
                tool_result_type_rules(),
                llm_format_rules(),
                llm_grounding_rules(),
                terminal_state_rules(),
                mutation_matcher_rules(),
            ]
        )
    )
    return draw(strategy)
