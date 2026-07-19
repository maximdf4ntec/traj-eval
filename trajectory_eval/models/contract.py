"""Generic output contract produced by the trajectory compiler.

This module defines the envelope and per-rule shape that the compiler emits.
It is intentionally decoupled from the internal :class:`~trajectory_eval.models.rule.Rule`
hierarchy (``polarity`` / ``scope`` / ``step_type`` / ``pseudocode``): those
fields describe *how a rule was derived*, while this contract describes
*what a downstream validator needs to evaluate it*.

Design principles (see project spec discussion):

* Every rule registers on the tuple ``(category, kind)``. ``category`` is a
  small, stable, closed vocabulary (:class:`RuleCategory`); ``kind`` is an
  open string because new evaluators are expected to introduce new kinds
  without requiring a schema change here.
* ``target`` says *what the rule applies to*. Most rules target a single
  ``(tool, parameter)`` or a ``response``, but some are trajectory-wide or
  span multiple steps/entities, so :class:`RuleTarget` accepts a small set
  of well-known optional fields and allows arbitrary extra keys for future
  target shapes.
* ``constraint`` is always rule-specific and opaque at this layer: the
  contract does not attempt to validate its internal shape. Only the
  concrete evaluator registered for a given ``(category, kind)`` knows how
  to read it.
* ``metadata`` is deliberately minimal: ``confidence`` and ``support`` only.

Splitting this single ``rules`` list into the two future compiler artifacts
(Behavior Contract vs. Execution Report) is out of scope here.
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


class RuleTarget(BaseModel):
    """What a rule applies to.

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
            trajectory as a whole (e.g. redundancy rate).
        step_index: A single specific step, when relevant.
        step_range: An inclusive ``(start, end)`` step index range, for
            rules spanning a window of steps.
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
    step_index: Optional[int] = None
    step_range: Optional[tuple[int, int]] = None
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
    """A single rule in the compiler output contract.

    Attributes:
        id: Unique identifier for this rule (e.g. ``"rule_001"``).
        category: Closed top-level classification, see :class:`RuleCategory`.
        kind: Open-ended sub-classification within ``category``; each
            evaluator registers on the ``(category, kind)`` pair.
        target: What this rule applies to.
        constraint: Rule-specific check parameters. Opaque at this layer —
            only the evaluator registered for ``(category, kind)`` reads it.
        metadata: Confidence/support metadata.
    """

    id: str
    category: RuleCategory
    kind: str
    target: RuleTarget
    constraint: dict[str, Any]
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


class TrajectoryContract(BaseModel):
    """Top-level envelope emitted by the trajectory compiler.

    Attributes:
        schema_version: Contract schema version; bump on breaking changes.
        generator: Identifies the compiler that produced this output.
        evidence: What the rules were compiled from.
        rules: The compiled rules.
    """

    schema_version: Literal[1] = 1
    generator: GeneratorInfo = Field(default_factory=GeneratorInfo)
    evidence: Evidence
    rules: list[CompiledRule]
