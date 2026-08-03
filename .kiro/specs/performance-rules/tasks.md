# Implementation Plan: Performance Rules

## Overview

Implement four new performance-oriented HardRule subclasses (TokenBudgetRule, LatencyBudgetRule, ToolOutputUtilizationRule, LlmResponseUtilizationRule) following the one-class-per-variant pattern. Each rule gets its own module file, is registered in the HardRuleRunner registry and YAML config, classified in the ContractCompiler, and exported from the rules `__init__.py`.

## Tasks

- [x] 1. Implement Budget Rules
  - [x] 1.1 Create `trajectory_eval/generator/rules/token_budget.py` with `TokenBudgetRule` class
    - Subclass `HardRule` with fields: `observed_tokens`, `threshold_tokens`, `token_budget_pct`
    - Implement `from_trajectory(trajectory, *, token_budget_pct=20.0, **kwargs)` classmethod that generates one rule per step with `token_count > 0`
    - Implement `model_validator(mode='after')` to derive `rule_description`, `pseudocode`, and `polarity`
    - Implement `generate()` returning `step[N].token_count <= threshold`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 7.1, 7.5, 7.6_

  - [x] 1.2 Create `trajectory_eval/generator/rules/latency_budget.py` with `LatencyBudgetRule` class
    - Subclass `HardRule` with fields: `observed_latency_ms`, `threshold_latency_ms`, `latency_budget_pct`
    - Implement `from_trajectory(trajectory, *, latency_budget_pct=50.0, **kwargs)` classmethod that generates one rule per step with `latency_ms > 0`
    - Implement `model_validator(mode='after')` to derive `rule_description`, `pseudocode`, and `polarity`
    - Implement `generate()` returning `step[N].latency_ms <= threshold`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 7.2, 7.5, 7.6_

  - [x]* 1.3 Write property tests for budget rules (`tests/test_budget_rules_properties.py`)
    - **Property 1: Budget threshold formula correctness** — for any step with positive metric and any pct >= 0, threshold == observed * (1 + pct/100)
    - **Property 2: Zero-value step exclusion** — no rule instances generated for steps with token_count == 0 or latency_ms == 0
    - **Property 3: Budget rule metadata invariants** — scope=step, confidence=high, step_type matches source, polarity=positive, rule_description and pseudocode non-empty
    - **Property 4: Budget rule generate() format** — output matches `step[N].token_count <= T` or `step[N].latency_ms <= T`
    - **Validates: Requirements 1.1, 1.2, 1.4, 1.6, 1.7, 2.1, 2.2, 2.4, 2.6, 2.7**

  - [x]* 1.4 Write unit tests for budget rules (`tests/test_budget_rules.py`)
    - Test empty trajectory produces no rules
    - Test single step with token_count=0 produces no TokenBudgetRule
    - Test custom token_budget_pct is applied correctly
    - Test custom latency_budget_pct is applied correctly
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3_

- [x] 2. Implement Utilization Rules
  - [x] 2.1 Create `trajectory_eval/generator/rules/tool_output_utilization.py` with `ToolOutputUtilizationRule` class
    - Subclass `HardRule` with fields: `tool_name`, `output_type`, `consumed_by_step`, `match_method`
    - Implement `from_trajectory(trajectory, **kwargs)` that generates rules for non-last tool_result steps with non-empty output
    - Implement structural matching (via `extract_facts`/`normalize_value` from FactNormalizer) for typed outputs
    - Implement content matching (substring on meaningful segments) for plain_text outputs
    - Implement `model_validator(mode='after')` to derive polarity (positive when consumed, negative when not), rule_description, and pseudocode
    - Add helper functions: `_detect_output_type_for_utilization`, `_find_consumer`, `_get_step_input_text`, `_extract_meaningful_segments`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 7.3, 7.5, 7.6_

  - [x] 2.2 Create `trajectory_eval/generator/rules/llm_response_utilization.py` with `LlmResponseUtilizationRule` class
    - Subclass `HardRule` with fields: `model_name`, `content_type`, `consumed_by_step`, `match_method`
    - Implement `from_trajectory(trajectory, **kwargs)` that generates rules for non-last llm_response steps with non-empty response
    - Implement structural matching for typed content (file_path, url, json, code) via typed fragment extraction
    - Implement content matching (substring on meaningful segments) for plain_text
    - Implement `model_validator(mode='after')` to derive polarity (positive when consumed, negative when not), rule_description, and pseudocode
    - Add helper functions: `_detect_llm_content_type`, `_find_llm_consumer`, `_extract_typed_fragments`, `_contains_file_paths`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 7.4, 7.5, 7.6_

  - [x]* 2.3 Write property tests for utilization rules (`tests/test_utilization_rules_properties.py`)
    - **Property 5: Utilization rule count for tool_result steps** — rule count equals non-last tool_result steps with non-empty output
    - **Property 6: Utilization rule count for llm_response steps** — rule count equals non-last llm_response steps with non-empty response
    - **Property 7: Utilization match method selection** — structural for {file_path, url, json, xml, number, code, yaml, date}, content for plain_text
    - **Property 8: Utilization polarity correctness** — positive iff consumed_by_step is not None, negative iff consumed_by_step is None
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5**

  - [x]* 2.4 Write unit tests for utilization rules (`tests/test_utilization_rules.py`)
    - Test empty trajectory produces no rules
    - Test single tool_result step (last step) is skipped
    - Test tool_result with empty output is skipped
    - Test structural match finds consumer for JSON output
    - Test content match finds consumer for plain_text output
    - Test LLM response with code blocks uses structural matching
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4_

- [x] 3. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Registration and Pipeline Integration
  - [x] 4.1 Update `trajectory_eval/generator/rules/__init__.py` to export the four new rule classes
    - Add imports for `TokenBudgetRule`, `LatencyBudgetRule`, `ToolOutputUtilizationRule`, `LlmResponseUtilizationRule`
    - Add all four to the `__all__` list
    - _Requirements: 6.5_

  - [x] 4.2 Update `trajectory_eval/generator/rule_runner.py` to register the four new rules in `_REGISTRY`
    - Add import for the four new classes from `trajectory_eval.generator.rules`
    - Add entries: `"token_budget"` → `TokenBudgetRule`, `"latency_budget"` → `LatencyBudgetRule`, `"tool_output_utilization"` → `ToolOutputUtilizationRule`, `"llm_response_utilization"` → `LlmResponseUtilizationRule`
    - _Requirements: 6.1_

  - [x] 4.3 Update `trajectory_eval/generator/hard_rules_config.yaml` to add the four new rule sections
    - Add `token_budget: { enabled: true, token_budget_pct: 20.0 }`
    - Add `latency_budget: { enabled: true, latency_budget_pct: 50.0 }`
    - Add `tool_output_utilization: { enabled: true }`
    - Add `llm_response_utilization: { enabled: true }`
    - _Requirements: 6.2, 3.1_

  - [x] 4.4 Update `trajectory_eval/generator/contract_compiler.py` to classify the four new rules
    - Import the four new classes
    - Add `TokenBudgetRule: _RuleArtifact.report` and `LatencyBudgetRule: _RuleArtifact.report`
    - Add `ToolOutputUtilizationRule: _RuleArtifact.contract` and `LlmResponseUtilizationRule: _RuleArtifact.contract`
    - _Requirements: 6.3, 6.4_

  - [x]* 4.5 Write integration tests (`tests/test_performance_rules_integration.py`)
    - Test `HardRuleRunner.run()` with a trajectory generates budget and utilization rules
    - Test `ContractCompiler.compile()` routes budget rules to report and utilization rules to contract
    - Test YAML config parsing loads the new rule entries correctly
    - Test registry lookup resolves all four rule names to their classes
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 5. Final Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation language is Python, matching the existing codebase
- All rule classes follow the existing one-class-per-variant pattern established by `ToolResultTypeRule` and other rules

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "2.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.3", "2.4"] },
    { "id": 2, "tasks": ["4.1", "4.2", "4.3", "4.4"] },
    { "id": 3, "tasks": ["4.5"] }
  ]
}
```
