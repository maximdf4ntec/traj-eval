# Requirements Document

## Introduction

Three new performance-oriented hard rules for the trajectory evaluation system. The Token/Latency Budget Rule enforces per-step resource consumption thresholds derived from observed trajectory data. The Tool Output Utilization Rule and LLM Response Utilization Rule verify that outputs produced during a trajectory are actually consumed downstream, detecting wasted computation.

All three rules follow the existing one-class-per-variant pattern (Pydantic BaseModel + ABC), register in the `HardRuleRunner` registry and YAML config, and integrate into the `compile_contract` pipeline.

## Glossary

- **RuleRunner**: The `HardRuleRunner` orchestrator that reads YAML config and dispatches `from_trajectory` on each enabled rule class.
- **CompileContract**: The `ContractCompiler` pipeline that classifies rules into contract-eligible or metrics-only and produces `BehaviorContract` and `ExecutionReport`.
- **TokenBudgetRule**: A HardRule subclass that asserts a step's token_count does not exceed a configurable percentage above the observed token_count from the reference trajectory.
- **LatencyBudgetRule**: A HardRule subclass that asserts a step's latency_ms does not exceed a configurable percentage above the observed latency_ms from the reference trajectory.
- **ToolOutputUtilizationRule**: A HardRule subclass that asserts a tool_result output is consumed by a subsequent step.
- **LlmResponseUtilizationRule**: A HardRule subclass that asserts an llm_response output is consumed by a subsequent step.
- **FactNormalizer**: The existing `trajectory_eval.generator.utils.fact_normalizer` module providing `extract_facts`, `normalize_value`, `is_candidate_value`, and `calculate_confidence` utilities.
- **OutputType**: The existing enum in `tool_result_type.py` classifying tool output content as json, xml, python, number, file_path, or plain_text.
- **StructuralMatch**: A matching strategy that uses typed output classification (file_path, url, json, etc.) to locate an output value in downstream step inputs via the FactNormalizer infrastructure.
- **ContentMatch**: A fallback matching strategy that uses substring or content matching to locate plain_text output in downstream step inputs or prompts.
- **Step**: A single node in a trajectory with attributes including `index`, `step_type`, `token_count`, `latency_ms`, `prompt`, `response`, and `tool`.

## Requirements

### Requirement 1: Token Budget Rule Generation

**User Story:** As an evaluator, I want per-step token budget rules generated from trajectory data, so that I can detect steps that consume disproportionately more tokens than observed.

#### Acceptance Criteria

1. WHEN a trajectory step has a `token_count` greater than zero, THE TokenBudgetRule SHALL generate one rule instance for that step with a threshold equal to the observed `token_count` multiplied by `(1 + token_budget_pct / 100)`.
2. WHEN a trajectory step has a `token_count` of zero, THE TokenBudgetRule SHALL NOT generate a rule instance for that step.
3. THE TokenBudgetRule SHALL accept a `token_budget_pct` configuration parameter from the YAML config specifying the percentage above observed value that triggers a violation.
4. THE TokenBudgetRule SHALL set `scope` to `step`, `step_type` to the step's actual type, and `confidence` to `high`.
5. THE TokenBudgetRule SHALL expose `observed_tokens`, `threshold_tokens`, and `token_budget_pct` as typed Pydantic fields.
6. THE TokenBudgetRule SHALL derive `rule_description` and `pseudocode` from its typed fields via a `model_validator(mode='after')`.
7. THE TokenBudgetRule SHALL implement `generate()` returning an assertion string of the form `step[N].token_count <= threshold`.

### Requirement 2: Latency Budget Rule Generation

**User Story:** As an evaluator, I want per-step latency budget rules generated from trajectory data, so that I can detect steps that take disproportionately longer than observed.

#### Acceptance Criteria

1. WHEN a trajectory step has a `latency_ms` greater than zero, THE LatencyBudgetRule SHALL generate one rule instance for that step with a threshold equal to the observed `latency_ms` multiplied by `(1 + latency_budget_pct / 100)`.
2. WHEN a trajectory step has a `latency_ms` of zero, THE LatencyBudgetRule SHALL NOT generate a rule instance for that step.
3. THE LatencyBudgetRule SHALL accept a `latency_budget_pct` configuration parameter from the YAML config specifying the percentage above observed value that triggers a violation.
4. THE LatencyBudgetRule SHALL set `scope` to `step`, `step_type` to the step's actual type, and `confidence` to `high`.
5. THE LatencyBudgetRule SHALL expose `observed_latency_ms`, `threshold_latency_ms`, and `latency_budget_pct` as typed Pydantic fields.
6. THE LatencyBudgetRule SHALL derive `rule_description` and `pseudocode` from its typed fields via a `model_validator(mode='after')`.
7. THE LatencyBudgetRule SHALL implement `generate()` returning an assertion string of the form `step[N].latency_ms <= threshold`.

### Requirement 3: Token and Latency Budget Independence

**User Story:** As an evaluator, I want token and latency thresholds to be independently configurable, so that I can tune each budget without affecting the other.

#### Acceptance Criteria

1. THE RuleRunner SHALL pass `token_budget_pct` to TokenBudgetRule and `latency_budget_pct` to LatencyBudgetRule as independent YAML-configured parameters.
2. WHEN only `token_budget_pct` is configured, THE RuleRunner SHALL generate TokenBudgetRule instances without requiring `latency_budget_pct`.
3. WHEN only `latency_budget_pct` is configured, THE RuleRunner SHALL generate LatencyBudgetRule instances without requiring `token_budget_pct`.

### Requirement 4: Tool Output Utilization Rule

**User Story:** As an evaluator, I want to verify that tool_result outputs are consumed by subsequent steps, so that I can identify wasted tool invocations.

#### Acceptance Criteria

1. WHEN a tool_result step produces non-empty output and is not the last tool_result step in the trajectory, THE ToolOutputUtilizationRule SHALL generate one rule instance for that step.
2. THE ToolOutputUtilizationRule SHALL NOT generate a rule instance for the last tool_result step in the trajectory.
3. WHEN the tool_result output has a detected type in the set {file_path, url, json, xml, number, code, yaml, date}, THE ToolOutputUtilizationRule SHALL use StructuralMatch to locate the output value in subsequent step tool inputs or prompts.
4. WHEN the tool_result output has detected type `plain_text`, THE ToolOutputUtilizationRule SHALL use ContentMatch (substring matching) to locate the output content in subsequent step tool inputs or prompts.
5. THE ToolOutputUtilizationRule SHALL set `polarity` to `positive` when at least one downstream step consumes the output and `negative` when no downstream step consumes it.
6. THE ToolOutputUtilizationRule SHALL expose `tool_name`, `output_type`, `consumed_by_step` (optional int), and `match_method` as typed Pydantic fields.
7. THE ToolOutputUtilizationRule SHALL reuse `extract_facts` and `normalize_value` from the FactNormalizer module for structural matching.
8. THE ToolOutputUtilizationRule SHALL be a standalone HardRule subclass that does not inherit from DataDependencyRule.

### Requirement 5: LLM Response Utilization Rule

**User Story:** As an evaluator, I want to verify that llm_response outputs are consumed by subsequent steps, so that I can identify wasted LLM invocations.

#### Acceptance Criteria

1. WHEN an llm_response step produces non-empty response content and is not the last llm_response step in the trajectory, THE LlmResponseUtilizationRule SHALL generate one rule instance for that step.
2. THE LlmResponseUtilizationRule SHALL NOT generate a rule instance for the last llm_response step in the trajectory.
3. WHEN the llm_response content contains identifiable typed fragments (file paths, URLs, JSON blocks, code blocks), THE LlmResponseUtilizationRule SHALL use StructuralMatch to locate those fragments in subsequent step tool inputs or prompts.
4. WHEN the llm_response content is unstructured plain text, THE LlmResponseUtilizationRule SHALL use ContentMatch (substring matching on meaningful segments) to locate the content in subsequent step tool inputs or prompts.
5. THE LlmResponseUtilizationRule SHALL set `polarity` to `positive` when at least one downstream step consumes the response and `negative` when no downstream step consumes it.
6. THE LlmResponseUtilizationRule SHALL expose `model_name` (optional str), `content_type`, `consumed_by_step` (optional int), and `match_method` as typed Pydantic fields.
7. THE LlmResponseUtilizationRule SHALL reuse `extract_facts` and `normalize_value` from the FactNormalizer module for structural matching.
8. THE LlmResponseUtilizationRule SHALL be a standalone HardRule subclass that does not inherit from DataDependencyRule.

### Requirement 6: Rule Registration and Pipeline Integration

**User Story:** As a developer, I want the new rules registered in the standard pipeline, so that they are generated alongside existing rules without special-case code.

#### Acceptance Criteria

1. THE RuleRunner registry SHALL include entries for `token_budget`, `latency_budget`, `tool_output_utilization`, and `llm_response_utilization` mapping to their respective rule classes.
2. THE YAML config SHALL include `token_budget`, `latency_budget`, `tool_output_utilization`, and `llm_response_utilization` sections with `enabled: true` and their respective configurable parameters.
3. THE ContractCompiler classification map SHALL route TokenBudgetRule and LatencyBudgetRule to the `report` artifact (metrics-only).
4. THE ContractCompiler classification map SHALL route ToolOutputUtilizationRule and LlmResponseUtilizationRule to the `contract` artifact.
5. THE rules `__init__.py` module SHALL export TokenBudgetRule, LatencyBudgetRule, ToolOutputUtilizationRule, and LlmResponseUtilizationRule.

### Requirement 7: One-Class-Per-Variant Pattern Compliance

**User Story:** As a developer, I want the new rules to follow established architectural patterns, so that the codebase remains consistent and maintainable.

#### Acceptance Criteria

1. THE TokenBudgetRule SHALL be a standalone class inheriting from HardRule, defined in its own module file.
2. THE LatencyBudgetRule SHALL be a standalone class inheriting from HardRule, defined in its own module file.
3. THE ToolOutputUtilizationRule SHALL be a standalone class inheriting from HardRule, defined in its own module file.
4. THE LlmResponseUtilizationRule SHALL be a standalone class inheriting from HardRule, defined in its own module file.
5. Each rule class SHALL implement `from_trajectory(trajectory, **kwargs) -> list[Self]` as the factory classmethod.
6. Each rule class SHALL use Pydantic `model_validator(mode='after')` to derive text fields from typed fields.
