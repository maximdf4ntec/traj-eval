from __future__ import annotations
from typing import Optional
from pydantic import model_validator
from trajectory_eval.models.rule import (
    ConfidenceLevel,
    HardRule,
    RulePolarity,
    RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.generator.utils.fact_normalizer import (
    extract_trackable_values,
)
from trajectory_eval.generator.rules.tool_result_type import (
    detect_output_type as _detect_result_output_type,
)


class LlmResponseUtilizationRule(HardRule):
    """Verifies llm_response output is consumed by a downstream step.

    Attributes:
        model_name: LLM model identifier (optional).
        content_type: Detected content type of the response.
        consumed_by_step: Index of the first downstream step consuming response, or None.
        match_method: "structural" or "content" depending on content_type.
    """

    model_name: Optional[str] = None
    content_type: str
    consumed_by_step: Optional[int] = None
    match_method: str

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = StepType.llm_response
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "LlmResponseUtilizationRule":
        if self.consumed_by_step is not None:
            self.polarity = RulePolarity.positive
            self.rule_description = (
                f"LLM response at step {self.step_index} "
                f"is consumed by step {self.consumed_by_step} "
                f"(matched via {self.match_method})."
            )
        else:
            self.polarity = RulePolarity.negative
            self.rule_description = (
                f"LLM response at step {self.step_index} "
                f"is NOT consumed by any downstream step."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        if self.consumed_by_step is not None:
            return (
                f"exists(step[j] for j > {self.step_index} where "
                f"step[j] consumes step[{self.step_index}].response)"
            )
        return (
            f"not exists(step[j] for j > {self.step_index} where "
            f"step[j] consumes step[{self.step_index}].response)"
        )

    @classmethod
    def from_trajectory(
        cls, trajectory: Trajectory, **kwargs
    ) -> list["LlmResponseUtilizationRule"]:
        steps = trajectory.steps
        llm_steps = [s for s in steps if s.step_type == StepType.llm_response]
        if not llm_steps:
            return []

        last_llm_idx = llm_steps[-1].index
        rules: list[LlmResponseUtilizationRule] = []

        for step in llm_steps:
            if step.index == last_llm_idx:
                continue  # Skip last llm_response step

            response = step.response or ""
            if not response.strip():
                continue

            content_type = _detect_llm_content_type(response)
            consumed_by = _find_llm_consumer(step, steps)

            rules.append(
                cls(
                    id=f"llm_response_util_{step.index}",
                    step_index=step.index,
                    polarity=RulePolarity.positive,  # overridden by validator
                    model_name=step.model_name,
                    content_type=content_type,
                    consumed_by_step=consumed_by,
                    match_method="content",
                )
            )

        return rules


def _detect_llm_content_type(response: str) -> str:
    """Detect content type of an LLM response using the canonical detector.

    Delegates to the same algorithm used by tool_result_type (Source B),
    ensuring consistency across all output-type classification in the system.
    """
    output_type, _method = _detect_result_output_type("llm_response", response)
    return output_type.value


def _find_llm_consumer(
    source_step: Step,
    all_steps: list[Step],
) -> Optional[int]:
    """Find the first downstream step that consumes the LLM response.

    Uses the same value-extraction algorithm as DataDependencyRule and
    ToolOutputUtilizationRule: extract atomic trackable values, then check
    if any appear as a substring in a downstream step's tool_input parameters.
    """
    response = source_step.response or ""
    if not response.strip():
        return None

    trackable_values = extract_trackable_values(response)
    if not trackable_values:
        return None

    for ds in all_steps:
        if ds.index <= source_step.index:
            continue
        target_text = _get_step_input_text(ds)
        if not target_text:
            continue
        for val in trackable_values:
            if val in target_text:
                return ds.index

    return None


def _get_step_input_text(step: Step) -> str:
    """Extract searchable text from a step's inputs (prompt + tool inputs)."""
    parts: list[str] = []
    if step.prompt:
        parts.append(step.prompt)
    if step.tool:
        for param in step.tool.inputs:
            parts.append(str(param.raw_value))
    return "\n".join(parts)
