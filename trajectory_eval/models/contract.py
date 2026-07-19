"""Behavior Contract — schema v2.

This module defines the envelope and per-rule shape that the contract compiler
emits.  It is intentionally decoupled from the internal
:class:`~trajectory_eval.models.rule.Rule` hierarchy (``polarity`` / ``scope``
/ ``step_type`` / ``pseudocode``): those fields describe *how a rule was
derived*, while this contract describes *what a downstream validator needs to
evaluate it*.

Design principles:

* Every rule registers on the tuple ``(category, kind)``. ``category`` is a
  small, stable, closed vocabulary (:class:`RuleCategory`); ``kind`` is an
  open string because new evaluators are expected to introduce new kinds
  without requiring a schema change here.
* ``target`` says *what the rule applies to* using abstract identifiers —
  tool names, parameter keys, tool-pair tuples, entity values, or
  trajectory-wide scope.  **No step indices.** Rules are expressed in terms
  that remain valid across trajectory variations that differ only in step
  ordering.
* ``constraint`` is always rule-specific and opaque at this layer: the
  contract does not attempt to validate its internal shape.  Only the
  concrete evaluator registered for a given ``(category, kind)`` knows how
  to read it.
* ``metadata`` is deliberately minimal: ``confidence`` and ``support`` only.
* ``cardinality`` specifies quantification: does the constraint hold for
  *every* instance of the target (``all``), *at least one* (``any``), or
  *exactly one specific* instance (``single``).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from trajectory_eval import __version__
from trajectory_eval.models.rule import ConfidenceLevel


class RuleCategory(str, Enum):
    """Closed, stable top-level classification for a rule.

    Attributes:
        provenance: Where a value came from (data lineage).
        workflow: Ordering/dependency between tool calls.
        interface: Type/shape/schema conformance of parameters or output.
        adaptation: Behavior change in response to failure or environment.
        grounding: Referential integrity against prior context.
        termination: Conditions describing how the trajectory ended.
    """

    provenance = "provenance"
    workflow = "workflow"
    interface = "interface"
    adaptation = "adaptation"
    grounding = "grounding"
    termination = "termination"


class RuleCardinality(str, Enum):
    """How many instances of the target the rule applies to.

    Attributes:
        all: Rule must hold for EVERY instance of the target.
        any: Rule must hold for AT LEAST ONE instance of the target.
        single: Rule applies to exactly one specific instance
            (e.g., the first or last occurrence).
    """

    all = "all"
    any = "any"
    single = "single"


class RuleTarget(BaseModel):
    """Abstract target — NO step indices.

    All fields are optional; a given rule populates only the ones relevant
    to its own ``(category, kind)``. Extra keys not listed here are allowed
    so new evaluators can introduce new target shapes without requiring a
    change to this model.

    Attributes:
        tool: Name of the tool the rule applies to.
        parameter: Name of a specific parameter of ``tool``.
        response: Marks the target as an assistant/LLM response
            (e.g. ``"assistant"``).
        scope: Set to ``"trajectory"`` when the rule applies to the
            trajectory as a whole (e.g. terminal state).
        tool_pair: A ``(tool_a, tool_b)`` pair, for rules about ordering or
            dependency between two tools.
        entity: A specific extracted entity (e.g. a file path or hash) the
            rule is grounding-checking.
    """

    model_config = ConfigDict(extra="allow")

    tool: Optional[str] = None
    parameter: Optional[str] = None
    response: Optional[str] = None
    scope: Optional[Literal["trajectory"]] = None
    tool_pair: Optional[tuple[str, str]] = None
    entity: Optional[str] = None


class RuleMetadata(BaseModel):
    """Minimal metadata attached to every rule.

    Attributes:
        confidence: Confidence level of the generated rule.
        support: Number of observations backing this rule. Becomes
            meaningful once rules are aggregated across multiple
            trajectories (currently always ``1``).
    """

    confidence: ConfidenceLevel
    support: int = Field(default=1, ge=1)


class CompiledRule(BaseModel):
    """A single rule in the Behavior Contract.

    Attributes:
        id: Unique identifier for this rule (e.g. ``"rule_001"``).
        category: Closed top-level classification, see :class:`RuleCategory`.
        kind: Open-ended sub-classification within ``category``; each
            evaluator registers on the ``(category, kind)`` pair.
        target: What this rule applies to (abstract, no step indices).
        constraint: Rule-specific check parameters. Opaque at this layer —
            only the evaluator registered for ``(category, kind)`` reads it.
        cardinality: Quantification — does the constraint hold for every
            instance of the target, at least one, or exactly one.
        metadata: Confidence/support metadata.
    """

    id: str
    category: RuleCategory
    kind: str
    target: RuleTarget
    constraint: dict[str, Any]
    cardinality: RuleCardinality
    metadata: RuleMetadata


class GeneratorInfo(BaseModel):
    """Identifies the compiler version that produced the output.

    Attributes:
        version: Version string of the ``trajectory_eval`` package.
    """

    version: str = __version__


class EvidenceSource(BaseModel):
    """Describes the evidence the rules were compiled from.

    Attributes:
        trajectory_count: Number of trajectories the rules were derived
            from. Always ``1`` until multi-trajectory aggregation exists.
    """

    trajectory_count: int = Field(default=1, ge=1)


class Evidence(BaseModel):
    """Wraps the evidence source for the compiled output.

    Attributes:
        generated_from: The evidence source.
    """

    generated_from: EvidenceSource


class BehaviorContract(BaseModel):
    """Top-level contract envelope — schema version 2.

    Contains deterministic, step-agnostic invariants suitable for regression
    testing and runtime validation.

    Attributes:
        schema_version: Contract schema version; always ``2`` for this format.
        generator: Identifies the compiler that produced this output.
        evidence: What the rules were compiled from.
        rules: The compiled rules (deduplicated global invariants).
    """

    schema_version: Literal[2] = 2
    generator: GeneratorInfo = Field(default_factory=GeneratorInfo)
    evidence: Evidence
    rules: list[CompiledRule]


class ContractParseError(Exception):
    """Raised when contract JSON cannot be parsed or validated."""

    pass


def parse_contract(json_str: str) -> BehaviorContract:
    """Parse and validate a JSON string into a BehaviorContract.

    Wraps Pydantic's model_validate_json with a domain-specific error.

    Args:
        json_str: A JSON string representing a BehaviorContract.

    Returns:
        A validated BehaviorContract instance.

    Raises:
        ContractParseError: When the JSON is invalid or doesn't conform to schema.
    """
    try:
        return BehaviorContract.model_validate_json(json_str)
    except Exception as e:
        raise ContractParseError(str(e)) from e
