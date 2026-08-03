# Design Document: Performance Rules

## Overview

Three new performance-oriented hard rules for the trajectory evaluation system: budget enforcement (token and latency) and output utilization verification (tool and LLM). All follow the one-class-per-variant pattern and integrate into the existing RuleRunner/ContractCompiler pipeline.

## Architecture

This feature adds four new `HardRule` subclasses to the trajectory evaluation system, following the established one-class-per-variant pattern. The rules fall into two categories:

1. **Budget Rules** — `TokenBudgetRule` and `LatencyBudgetRule` enforce per-step resource consumption thresholds derived from observed trajectory data. They are classified as metrics-only and route to the `ExecutionReport`.

2. **Utilization Rules** — `ToolOutputUtilizationRule` and `LlmResponseUtilizationRule` verify that outputs produced during a trajectory are consumed by downstream steps, detecting wasted computation. They are classified as contract-eligible and route to the `BehaviorContract`.

All four classes integrate into the existing `HardRuleRunner` dispatch pipeline via YAML config entries and registry additions.

## Components and Interfaces

### 1. TokenBudgetRule (`trajectory_eval/generator/rules/token_budget.py`)

A `HardRule` subclass that asserts a step's `token_count` does not exceed a configurable percentage above the observed value.

```python
from __future__ import annotations
from typing import Optional
from pydantic import model_validator
from trajectory_eval.models.rule import (
    ConfidenceLevel, HardRule, RulePolarity, RuleScope,
)
from trajectory_eval.models.trajectory import StepType, Trajectory


class TokenBudgetRule(HardRule):
    """Per-step token budget enforcement rule.

    Attributes:
        observed_tokens: Token count observed in the reference step.
        threshold_tokens: Maximum allowed token count (inclusive).
        token_budget_pct: Percentage above observed that defines the threshold.
    """

    observed_tokens: int
    threshold_tokens: float
    token_budget_pct: float

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = None
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "TokenBudgetRule":
        self.polarity = RulePolarity.positive
        self.rule_description = (
            f"Step {self.step_index} token_count must not exceed "
            f"{self.threshold_tokens:.0f} "
            f"(observed {self.observed_tokens} + {self.token_budget_pct}% budget)."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        return (
            f"step[{self.step_index}].token_count <= {self.threshold_tokens:.0f}"
        )

    @classmethod
    def from_trajectory(
        cls, trajectory: Trajectory, *, token_budget_pct: float = 20.0, **kwargs
    ) -> list["TokenBudgetRule"]:
        rules: list[TokenBudgetRule] = []
        for step in trajectory.steps:
            if step.token_count <= 0:
                continue
            threshold = step.token_count * (1 + token_budget_pct / 100)
            rules.append(
                cls(
                    id=f"token_budget_{step.index}",
                    step_index=step.index,
                    polarity=RulePolarity.positive,
                    step_type=step.step_type,
                    observed_tokens=step.token_count,
                    threshold_tokens=threshold,
                    token_budget_pct=token_budget_pct,
                )
            )
        return rules
```

### 2. LatencyBudgetRule (`trajectory_eval/generator/rules/latency_budget.py`)

A `HardRule` subclass that asserts a step's `latency_ms` does not exceed a configurable percentage above the observed value.

```python
from __future__ import annotations
from typing import Optional
from pydantic import model_validator
from trajectory_eval.models.rule import (
    ConfidenceLevel, HardRule, RulePolarity, RuleScope,
)
from trajectory_eval.models.trajectory import StepType, Trajectory


class LatencyBudgetRule(HardRule):
    """Per-step latency budget enforcement rule.

    Attributes:
        observed_latency_ms: Latency observed in the reference step.
        threshold_latency_ms: Maximum allowed latency (inclusive).
        latency_budget_pct: Percentage above observed that defines the threshold.
    """

    observed_latency_ms: int
    threshold_latency_ms: float
    latency_budget_pct: float

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = None
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "LatencyBudgetRule":
        self.polarity = RulePolarity.positive
        self.rule_description = (
            f"Step {self.step_index} latency_ms must not exceed "
            f"{self.threshold_latency_ms:.0f} "
            f"(observed {self.observed_latency_ms} + {self.latency_budget_pct}% budget)."
        )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        return (
            f"step[{self.step_index}].latency_ms <= {self.threshold_latency_ms:.0f}"
        )

    @classmethod
    def from_trajectory(
        cls, trajectory: Trajectory, *, latency_budget_pct: float = 50.0, **kwargs
    ) -> list["LatencyBudgetRule"]:
        rules: list[LatencyBudgetRule] = []
        for step in trajectory.steps:
            if step.latency_ms <= 0:
                continue
            threshold = step.latency_ms * (1 + latency_budget_pct / 100)
            rules.append(
                cls(
                    id=f"latency_budget_{step.index}",
                    step_index=step.index,
                    polarity=RulePolarity.positive,
                    step_type=step.step_type,
                    observed_latency_ms=step.latency_ms,
                    threshold_latency_ms=threshold,
                    latency_budget_pct=latency_budget_pct,
                )
            )
        return rules
```

### 3. ToolOutputUtilizationRule (`trajectory_eval/generator/rules/tool_output_utilization.py`)

A `HardRule` subclass that verifies tool_result outputs are consumed by subsequent steps.

```python
from __future__ import annotations
from typing import Optional
from pydantic import model_validator
from trajectory_eval.models.rule import (
    ConfidenceLevel, HardRule, RulePolarity, RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.models.tool import ParameterType
from trajectory_eval.generator.utils.fact_normalizer import extract_facts, normalize_value


# Types considered "structured" for StructuralMatch
_STRUCTURAL_TYPES: frozenset[str] = frozenset([
    "file_path", "url", "json", "xml", "number", "code", "yaml", "date",
])


class ToolOutputUtilizationRule(HardRule):
    """Verifies tool_result output is consumed by a downstream step.

    Attributes:
        tool_name: Name of the tool that produced the output.
        output_type: Detected content type of the output.
        consumed_by_step: Index of the first downstream step consuming output, or None.
        match_method: "structural" or "content" depending on output_type.
    """

    tool_name: str
    output_type: str
    consumed_by_step: Optional[int] = None
    match_method: str

    scope: RuleScope = RuleScope.step
    step_type: Optional[StepType] = StepType.tool_result
    confidence: ConfidenceLevel = ConfidenceLevel.high

    rule_description: str = ""
    pseudocode: str = ""

    @model_validator(mode="after")
    def _derive_text_fields(self) -> "ToolOutputUtilizationRule":
        if self.consumed_by_step is not None:
            self.polarity = RulePolarity.positive
            self.rule_description = (
                f"Tool '{self.tool_name}' output at step {self.step_index} "
                f"is consumed by step {self.consumed_by_step} "
                f"(matched via {self.match_method})."
            )
        else:
            self.polarity = RulePolarity.negative
            self.rule_description = (
                f"Tool '{self.tool_name}' output at step {self.step_index} "
                f"is NOT consumed by any downstream step."
            )
        self.pseudocode = self.generate()
        return self

    def generate(self) -> str:
        if self.consumed_by_step is not None:
            return (
                f"exists(step[j] for j > {self.step_index} where "
                f"step[j] consumes step[{self.step_index}].tool_output)"
            )
        return (
            f"not exists(step[j] for j > {self.step_index} where "
            f"step[j] consumes step[{self.step_index}].tool_output)"
        )

    @classmethod
    def from_trajectory(
        cls, trajectory: Trajectory, **kwargs
    ) -> list["ToolOutputUtilizationRule"]:
        steps = trajectory.steps
        # Find all tool_result steps
        tool_result_steps = [s for s in steps if s.step_type == StepType.tool_result]
        if not tool_result_steps:
            return []

        last_tool_result_idx = tool_result_steps[-1].index
        rules: list[ToolOutputUtilizationRule] = []

        for step in tool_result_steps:
            if step.index == last_tool_result_idx:
                continue  # Skip last tool_result step

            output = step.tool_output or ""
            if not output.strip():
                continue

            tool_name = step.tool_name or ""
            output_type = _detect_output_type_for_utilization(step)
            match_method = (
                "structural" if output_type in _STRUCTURAL_TYPES else "content"
            )
            consumed_by = _find_consumer(step, steps, output_type, match_method)

            rules.append(
                cls(
                    id=f"tool_output_util_{step.index}",
                    step_index=step.index,
                    polarity=RulePolarity.positive,  # overridden by validator
                    tool_name=tool_name,
                    output_type=output_type,
                    consumed_by_step=consumed_by,
                    match_method=match_method,
                )
            )

        return rules


def _detect_output_type_for_utilization(step: Step) -> str:
    """Detect output type using the Tool's output_typed field or fallback heuristics."""
    if step.tool and step.tool.output_typed:
        return step.tool.output_typed.detected_type.value
    # Fallback: use content heuristics from FactNormalizer
    output = step.tool_output or ""
    normalized = normalize_value(output)
    if not normalized:
        return "plain_text"
    # Simple heuristic checks
    if normalized.startswith("/") or "\\" in normalized:
        return "file_path"
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return "url"
    if normalized.startswith("{") or normalized.startswith("["):
        return "json"
    if normalized.startswith("<"):
        return "xml"
    return "plain_text"


def _find_consumer(
    source_step: Step,
    all_steps: list[Step],
    output_type: str,
    match_method: str,
) -> Optional[int]:
    """Find the first downstream step that consumes the source output."""
    output = source_step.tool_output or ""
    if not output.strip():
        return None

    downstream = [s for s in all_steps if s.index > source_step.index]

    if match_method == "structural":
        facts = extract_facts(output if output_type == "json" else output.strip())
        fact_values = {f.value_str for f in facts} if facts else {normalize_value(output)}
        for ds in downstream:
            target_text = _get_step_input_text(ds)
            for val in fact_values:
                if val and val in target_text:
                    return ds.index
    else:
        # ContentMatch: substring matching on meaningful segments
        segments = _extract_meaningful_segments(output)
        for ds in downstream:
            target_text = _get_step_input_text(ds)
            for seg in segments:
                if seg in target_text:
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


def _extract_meaningful_segments(text: str, min_len: int = 8) -> list[str]:
    """Extract meaningful substrings from plain text for content matching."""
    lines = [l.strip() for l in text.strip().splitlines() if len(l.strip()) >= min_len]
    return lines[:10]  # Cap to avoid excessive comparisons
```

### 4. LlmResponseUtilizationRule (`trajectory_eval/generator/rules/llm_response_utilization.py`)

A `HardRule` subclass that verifies llm_response outputs are consumed by subsequent steps.

```python
from __future__ import annotations
from typing import Optional
from pydantic import model_validator
from trajectory_eval.models.rule import (
    ConfidenceLevel, HardRule, RulePolarity, RuleScope,
)
from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.generator.utils.fact_normalizer import extract_facts, normalize_value


# Types considered "structured" for StructuralMatch in LLM responses
_STRUCTURAL_TYPES: frozenset[str] = frozenset([
    "file_path", "url", "json", "xml", "number", "code", "yaml", "date",
])


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
            match_method = (
                "structural" if content_type in _STRUCTURAL_TYPES else "content"
            )
            consumed_by = _find_llm_consumer(step, steps, content_type, match_method)

            rules.append(
                cls(
                    id=f"llm_response_util_{step.index}",
                    step_index=step.index,
                    polarity=RulePolarity.positive,  # overridden by validator
                    model_name=step.model_name,
                    content_type=content_type,
                    consumed_by_step=consumed_by,
                    match_method=match_method,
                )
            )

        return rules


def _detect_llm_content_type(response: str) -> str:
    """Detect dominant content type in an LLM response."""
    stripped = response.strip()
    # Check for structured fragments
    if _contains_file_paths(stripped):
        return "file_path"
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return "url"
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if "```" in stripped:
        return "code"
    if stripped.startswith("<") and stripped.endswith(">"):
        return "xml"
    return "plain_text"


def _contains_file_paths(text: str) -> bool:
    """Check if text contains identifiable file paths."""
    import re
    return bool(re.search(r"(?:^|[\s\n])(/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10})", text))


def _find_llm_consumer(
    source_step: Step,
    all_steps: list[Step],
    content_type: str,
    match_method: str,
) -> Optional[int]:
    """Find the first downstream step that consumes the LLM response."""
    response = source_step.response or ""
    if not response.strip():
        return None

    downstream = [s for s in all_steps if s.index > source_step.index]

    if match_method == "structural":
        fragments = _extract_typed_fragments(response, content_type)
        for ds in downstream:
            target_text = _get_step_input_text(ds)
            for frag in fragments:
                normalized = normalize_value(frag)
                if normalized and normalized in target_text:
                    return ds.index
    else:
        segments = _extract_meaningful_segments(response)
        for ds in downstream:
            target_text = _get_step_input_text(ds)
            for seg in segments:
                if seg in target_text:
                    return ds.index

    return None


def _extract_typed_fragments(response: str, content_type: str) -> list[str]:
    """Extract typed fragments from LLM response for structural matching."""
    import re
    fragments: list[str] = []
    if content_type == "file_path":
        fragments = re.findall(r"/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10}", response)
    elif content_type == "url":
        fragments = re.findall(r"https?://[^\s\"'<>]+", response)
    elif content_type == "json":
        fragments = [response.strip()]
    elif content_type == "code":
        # Extract code block contents
        blocks = re.findall(r"```[\w]*\n(.*?)```", response, re.DOTALL)
        fragments = blocks if blocks else [response.strip()]
    else:
        fragments = [response.strip()]
    return fragments[:10]


def _get_step_input_text(step: Step) -> str:
    """Extract searchable text from a step's inputs."""
    parts: list[str] = []
    if step.prompt:
        parts.append(step.prompt)
    if step.tool:
        for param in step.tool.inputs:
            parts.append(str(param.raw_value))
    return "\n".join(parts)


def _extract_meaningful_segments(text: str, min_len: int = 8) -> list[str]:
    """Extract meaningful substrings from plain text for content matching."""
    lines = [l.strip() for l in text.strip().splitlines() if len(l.strip()) >= min_len]
    return lines[:10]
```

### Factory Method Contract (all four rule classes)

All four rule classes implement the same factory interface:

```python
@classmethod
def from_trajectory(
    cls, trajectory: Trajectory, **kwargs
) -> list[Self]:
    ...
```

**Budget rules** accept their respective `*_budget_pct` parameter via `**kwargs` (passed from YAML config by `HardRuleRunner`).

**Utilization rules** accept no additional parameters beyond the trajectory.

### RuleRunner Registry Additions

```python
# In rule_runner.py _REGISTRY dict:
from trajectory_eval.generator.rules import (
    TokenBudgetRule,
    LatencyBudgetRule,
    ToolOutputUtilizationRule,
    LlmResponseUtilizationRule,
)

_REGISTRY["token_budget"] = TokenBudgetRule
_REGISTRY["latency_budget"] = LatencyBudgetRule
_REGISTRY["tool_output_utilization"] = ToolOutputUtilizationRule
_REGISTRY["llm_response_utilization"] = LlmResponseUtilizationRule
```

### ContractCompiler Classification Additions

```python
# In contract_compiler.py _CLASSIFICATION dict:
from trajectory_eval.generator.rules import (
    TokenBudgetRule,
    LatencyBudgetRule,
    ToolOutputUtilizationRule,
    LlmResponseUtilizationRule,
)

_CLASSIFICATION[TokenBudgetRule] = _RuleArtifact.report
_CLASSIFICATION[LatencyBudgetRule] = _RuleArtifact.report
_CLASSIFICATION[ToolOutputUtilizationRule] = _RuleArtifact.contract
_CLASSIFICATION[LlmResponseUtilizationRule] = _RuleArtifact.contract
```

### YAML Config Additions

```yaml
# In hard_rules_config.yaml under trajectory_rules:
token_budget:
  enabled: true
  token_budget_pct: 20.0

latency_budget:
  enabled: true
  latency_budget_pct: 50.0

tool_output_utilization:
  enabled: true

llm_response_utilization:
  enabled: true
```

## Data Models

All four rule classes are Pydantic `BaseModel` subclasses (via `HardRule`) with typed fields. The key data flows:

```
Trajectory.steps[i].token_count → TokenBudgetRule.observed_tokens
Trajectory.steps[i].latency_ms  → LatencyBudgetRule.observed_latency_ms
Trajectory.steps[i].tool_output → ToolOutputUtilizationRule (via FactNormalizer)
Trajectory.steps[i].response    → LlmResponseUtilizationRule (via FactNormalizer)
```

### Matching Strategy Selection

| Output Type | Match Method | Lookup Approach |
|---|---|---|
| file_path, url, json, xml, number, code, yaml, date | `structural` | `extract_facts` + `normalize_value` from FactNormalizer |
| plain_text | `content` | Substring matching on meaningful segments |

## Error Handling

- **Zero-value steps**: Budget rules silently skip steps with `token_count <= 0` or `latency_ms <= 0` — no rule generated, no error raised.
- **Empty output**: Utilization rules skip steps with empty/whitespace-only output.
- **Last step exclusion**: Utilization rules skip the last step of their type (no downstream to consume it).
- **FactNormalizer failures**: If `extract_facts` returns empty results for structured content, the utilization rule falls back to treating the output as a single normalized value for matching.
- **Runner fault tolerance**: Existing `HardRuleRunner` error handling (try/except per rule) applies — one rule failure does not block others.

## Testing Strategy

- **Property-based tests** (Hypothesis): Validate universal properties (threshold formula, zero-value exclusion, metadata invariants, polarity correctness, match method selection, rule count invariants) across randomly generated trajectories with varying step counts, token values, latency values, and output content.
- **Unit tests** (pytest): Verify specific examples — YAML config parsing, registry presence, classification routing, module exports, class hierarchy, and edge cases (empty trajectories, single-step trajectories).
- **Integration tests**: Run the full `HardRuleRunner.run()` pipeline with test YAML configs containing the new rule entries and verify end-to-end rule generation.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Budget threshold formula correctness

*For any* trajectory step with a positive metric value (token_count > 0 or latency_ms > 0) and *for any* budget percentage `pct` ≥ 0, the generated budget rule's threshold field SHALL equal exactly `observed_value * (1 + pct / 100)`.

**Validates: Requirements 1.1, 2.1**

### Property 2: Zero-value step exclusion

*For any* trajectory containing steps where token_count == 0 or latency_ms == 0, the corresponding budget rule's `from_trajectory` SHALL produce no rule instances referencing those steps. The set of generated rule step_indices SHALL be a subset of step indices with positive metric values.

**Validates: Requirements 1.2, 2.2**

### Property 3: Budget rule metadata invariants

*For any* generated budget rule (TokenBudgetRule or LatencyBudgetRule), `scope` SHALL be `step`, `confidence` SHALL be `high`, `step_type` SHALL equal the source step's `step_type`, `polarity` SHALL be `positive`, and both `rule_description` and `pseudocode` SHALL be non-empty strings.

**Validates: Requirements 1.4, 1.6, 2.4, 2.6**

### Property 4: Budget rule generate() format

*For any* generated TokenBudgetRule, `generate()` SHALL return a string matching the pattern `step[N].token_count <= T` where N is the step_index and T is the threshold. *For any* generated LatencyBudgetRule, `generate()` SHALL return a string matching `step[N].latency_ms <= T`.

**Validates: Requirements 1.7, 2.7**

### Property 5: Utilization rule count for tool_result steps

*For any* trajectory, the number of `ToolOutputUtilizationRule` instances generated SHALL equal the count of tool_result steps that have non-empty output AND are not the last tool_result step in the trajectory. No rule SHALL reference the last tool_result step's index.

**Validates: Requirements 4.1, 4.2**

### Property 6: Utilization rule count for llm_response steps

*For any* trajectory, the number of `LlmResponseUtilizationRule` instances generated SHALL equal the count of llm_response steps that have non-empty response AND are not the last llm_response step in the trajectory. No rule SHALL reference the last llm_response step's index.

**Validates: Requirements 5.1, 5.2**

### Property 7: Utilization match method selection

*For any* utilization rule (ToolOutputUtilizationRule or LlmResponseUtilizationRule), if the detected output/content type is in the set {file_path, url, json, xml, number, code, yaml, date}, then `match_method` SHALL be `"structural"`. If the detected type is `plain_text`, then `match_method` SHALL be `"content"`.

**Validates: Requirements 4.3, 4.4, 5.3, 5.4**

### Property 8: Utilization polarity correctness

*For any* utilization rule (ToolOutputUtilizationRule or LlmResponseUtilizationRule), `polarity` SHALL be `positive` if and only if `consumed_by_step` is not None, and `negative` if and only if `consumed_by_step` is None.

**Validates: Requirements 4.5, 5.5**
