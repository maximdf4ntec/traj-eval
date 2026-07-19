"""Rule Pydantic models — abstract base and hard/soft subclasses.

Class hierarchy:

    Rule (abstract, BaseModel + ABC)
    ├── HardRule  — deterministic, no LLM
    └── SoftRule  — requires LLM-based judgement

Concrete rule implementations (one class per logical check) will subclass
HardRule or SoftRule and override ``generate()`` to compute the assertion
expression dynamically from their own fields.  Until those concrete classes
exist, the stored ``pseudocode`` field acts as a direct return value.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel

from trajectory_eval.models.trajectory import StepType


class RulePolarity(str, Enum):
    """Whether a rule asserts a positive or negative condition.

    Attributes:
        positive: The described condition should hold.
        negative: The described condition should *not* hold.
        neutral: The rule applies regardless of step polarity.
    """

    positive = "positive"
    negative = "negative"
    neutral = "neutral"


class RuleScope(str, Enum):
    """Granularity at which a rule applies.

    Attributes:
        step: Applies to a single trajectory step.
        frame: Applies to a group of related steps
            (e.g. a ``tool_call`` + ``tool_result`` pair).
        global_: Applies to the trajectory as a whole.
    """

    step = "step"
    frame = "frame"
    global_ = "global"


class ConfidenceLevel(str, Enum):
    """Confidence level assigned to a generated rule.

    Attributes:
        high: Derived directly from trajectory data; almost always correct.
        medium: Heuristic or LLM-derived; generally reliable.
        low: Weakly supported; treat as a hint.
    """

    high = "high"
    medium = "medium"
    low = "low"


class Rule(BaseModel, ABC):
    """Abstract base class for all trajectory evaluation rules.

    A Rule describes one evaluatable assertion about a trajectory step or
    a group of steps.  Subclasses must implement :meth:`generate` to return
    the pseudocode / assertion expression for the rule.

    Attributes:
        id: Unique identifier for this rule instance
            (e.g. ``"tool_call_3_1"``).
        step_index: Zero-based index of the primary target step;
            ``None`` for global-scope rules.
        polarity: Whether the rule asserts a positive or negative condition.
        scope: Granularity at which this rule applies.
        step_type: The :class:`~trajectory_eval.models.trajectory.StepType`
            this rule targets; ``None`` for global-scope rules.
        confidence: Confidence level of the generated rule.
        rule_description: Plain-English description of what this rule checks.
            Concrete subclasses may leave this empty and derive it in a
            ``model_validator(mode='after')`` from their typed fields.
    """

    id: str
    step_index: Optional[int]
    polarity: RulePolarity
    scope: RuleScope
    step_type: Optional[StepType]
    confidence: ConfidenceLevel
    rule_description: str = ""

    @abstractmethod
    def generate(self) -> str:
        """Generate the pseudocode / assertion expression for this rule.

        Returns:
            A human-readable string representing the rule's assertion logic.
        """
        ...

    def to_string(self) -> str:
        """Return a human-readable string representation of this rule.

        Includes rule ID, step index, type, polarity, scope, confidence,
        description, and pseudocode.

        Returns:
            A nicely formatted multi-line string describing the rule.
        """
        lines = [
            f"[{self.id}] {self.rule_description}",
            f"  Step: {self.step_index}, Type: {self.step_type}, "
            f"Scope: {self.scope}, Polarity: {self.polarity}",
            f"  Confidence: {self.confidence}",
            f"  Assertion: {self.generate()}",
        ]
        return "\n".join(lines)


class HardRule(Rule):
    """A deterministically evaluatable rule requiring no LLM.

    Hard rules are derived directly from trajectory data via structural
    checks (equality, key presence, type checks).  The ``pseudocode`` field
    stores the assertion expression until a concrete subclass overrides
    :meth:`generate` to compute it dynamically.

    Attributes:
        rule_type: Discriminator literal, always ``"hard"``.
        pseudocode: Precomputed assertion expression returned by
            :meth:`generate`.
    """

    rule_type: Literal["hard"] = "hard"
    pseudocode: str = ""

    def generate(self) -> str:
        """Return the stored pseudocode assertion for this hard rule.

        Concrete subclasses override this to compute the assertion
        dynamically from their own typed fields.

        Returns:
            The ``pseudocode`` field value.
        """
        return self.pseudocode


class SoftRule(Rule):
    """A rule whose evaluation requires LLM-based judgement.

    Soft rules express qualitative conditions that cannot be checked
    deterministically from the raw trajectory data alone.  The ``pseudocode``
    field stores the assertion expression until a concrete subclass overrides
    :meth:`generate` to compute it dynamically.

    Attributes:
        rule_type: Discriminator literal, always ``"soft"``.
        pseudocode: Precomputed assertion expression returned by
            :meth:`generate`.
    """

    rule_type: Literal["soft"] = "soft"
    pseudocode: str

    def generate(self) -> str:
        """Return the stored pseudocode assertion for this soft rule.

        Returns:
            The ``pseudocode`` field value.
        """
        return self.pseudocode
