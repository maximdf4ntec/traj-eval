# Implementation Plan: Contract Redesign

## Overview

Restructure the trajectory evaluation compiler output into two distinct artifacts: a Behavior Contract (deterministic, step-agnostic invariants) and an Execution Report (behavioral observations and metrics). This involves creating new orchestrator/deduplication/emitter/report modules, modifying existing rule classes and models, removing ToolIndexRule, and promoting per-step rules to trajectory-level factories.

## Tasks

- [ ] 1. Update data models and schema
  - [ ] 1.1 Update `trajectory_eval/models/contract.py` — schema v2 models
    - Remove `step_index` and `step_range` fields from `RuleTarget`
    - Add `tool_pair`, `entity`, `scope`, and `response` fields to `RuleTarget`
    - Add `RuleCardinality` enum with values `all`, `any`, `single`
    - Add `cardinality` field to `CompiledRule`
    - Bump `BehaviorContract.schema_version` to `Literal[2]`
    - Add `GeneratorInfo` to reflect package version
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 2.5_

  - [ ] 1.2 Create `trajectory_eval/models/execution_report.py` — ExecutionReport model
    - Define `MetricObservation` model with `rule_class`, `category`, and `observation` fields
    - Define `InconsistencyFlag` model with `target_fingerprint`, `category`, `kind`, `conflicting_constraints`, and `observation_count` fields
    - Define `ExecutionReport` model with `schema_version`, `generator`, `metrics`, and `flags` fields
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [ ] 1.3 Update `trajectory_eval/models/__init__.py` — export new models
    - Export `ExecutionReport`, `MetricObservation`, `InconsistencyFlag`, `RuleCardinality`
    - _Requirements: 13.1_

- [ ] 2. Implement RuleEmitter
  - [ ] 2.1 Create `trajectory_eval/generator/emitter.py` — emitter registry and functions
    - Implement `EmitterFn` type alias
    - Implement `_EMITTER_REGISTRY` mapping rule classes to emitter functions
    - Implement `emit_data_dependency` — converts DataDependencyRule to CompiledRule with `must_originate_from` constraint, no step indices
    - Implement `emit_tool_sequence` — converts ToolSequenceRule to CompiledRule with `tool_pair` target and `condition`/`behavior` constraint
    - Implement `emit_param_type` — converts ToolParamTypeRule to CompiledRule with `expected_type` constraint
    - Implement `emit_param_count` — converts ToolParamCountRule to CompiledRule with `expected_count` constraint
    - Implement `emit_result_type` — converts ToolResultTypeRule to CompiledRule with `expected_format` constraint
    - Implement `emit_llm_format` — converts LlmResponseFormatRule to CompiledRule with `response: "assistant"` target
    - Implement `emit_llm_grounding` — converts LlmGroundingRule to CompiledRule with `entity` target
    - Implement `emit_terminal_state` — converts TerminalStateRule to CompiledRule with `scope: "trajectory"` target, `cardinality: single`
    - Implement `emit_mutation_matcher` — converts MutationMatcherRule to CompiledRule with `category: adaptation`, `kind: failure_recovery`
    - Implement public `emit(rule: HardRule) -> CompiledRule` dispatch function
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 12.4_

  - [ ]* 2.2 Write property test for emitter (Property 7: Correct Abstract Structure)
    - **Property 7: Emitter Produces Correct Abstract Structure**
    - **Validates: Requirements 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 10.1–10.8, 11.1–11.4, 12.1, 12.2, 12.4**

  - [ ]* 2.3 Write property test for step-index elimination (Property 2)
    - **Property 2: Step-Index Elimination**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

- [ ] 3. Implement RuleDeduplicator
  - [ ] 3.1 Create `trajectory_eval/generator/deduplicator.py` — deduplication logic
    - Implement `RuleDeduplicator` class with `deduplicate(rules: list[CompiledRule]) -> DeduplicationResult` method
    - Implement `DeduplicationResult` dataclass with `rules` and `flags` fields
    - Implement `_identity_key` — canonical fingerprint from `(category, kind, sorted target JSON)`
    - Implement `_all_consistent` — check all constraint dicts in a group are identical
    - Implement merge logic: set `support = len(group)`, `confidence = max(group confidences)`
    - Implement inconsistency detection: emit `InconsistencyFlag` when constraints conflict
    - Implement sequential ID assignment: `rule_001`, `rule_002`, etc.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 8.4, 9.4, 12.3_

  - [ ]* 3.2 Write property test for deduplication merging (Property 4)
    - **Property 4: Deduplication Merges Identical Rules**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.5, 6.6, 8.4, 9.4, 12.3**

  - [ ]* 3.3 Write property test for sequential IDs (Property 5)
    - **Property 5: Deduplication IDs Are Sequential and Unique**
    - **Validates: Requirements 6.4**

  - [ ]* 3.4 Write property test for conflicting rules (Property 6)
    - **Property 6: Conflicting Rules Produce Flags, Not Contract Rules**
    - **Validates: Requirements 7.1, 7.2, 7.3**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement ToolSequence confidence heuristic
  - [ ] 5.1 Modify `trajectory_eval/generator/rules/tool_sequence.py` — add confidence heuristic
    - Implement `_compute_confidence` function with three signals: data-flow, powerful couples, count threshold
    - Add `powerful_couples` parameter support (loaded from YAML config)
    - Add `confidence_threshold` parameter (default 3)
    - Suppress rules below threshold without structural evidence
    - Detect inconsistent ordering and skip (route to flags)
    - Implement data-flow cross-reference lookup against DataDependencyRule instances
    - _Requirements: 9.5, 9.6, 9.7, 9.8, 9.9_

  - [ ]* 5.2 Write property test for confidence heuristic (Property 8)
    - **Property 8: Confidence Heuristic — Any Qualifying Signal Yields High**
    - **Validates: Requirements 9.5, 9.6, 9.7**

  - [ ]* 5.3 Write property test for below-threshold suppression (Property 9)
    - **Property 9: Below-Threshold Pairs Are Suppressed**
    - **Validates: Requirements 9.8**

- [ ] 6. Promote per-step rules to trajectory-level
  - [ ] 6.1 Modify `trajectory_eval/generator/rules/tool_checks.py` — add `from_trajectory` classmethods
    - Add `ToolParamTypeRule.from_trajectory(trajectory)` — scan all tool_call steps, collect type observations per (tool, param) pair
    - Add `ToolParamCountRule.from_trajectory(trajectory)` — scan all tool_call steps, collect param count per tool
    - Delete `from_step` methods entirely (not in use)
    - Delete `ToolIndexRule` class entirely
    - _Requirements: 5.1, 5.2, 5.3, 15.1, 15.2, 15.3_

  - [ ] 6.2 Modify `trajectory_eval/generator/rules/__init__.py` — remove ToolIndexRule export
    - Remove `ToolIndexRule` from `__all__` and any re-export
    - _Requirements: 5.1_

- [ ] 7. Implement ReportBuilder
  - [ ] 7.1 Create `trajectory_eval/generator/report_builder.py` — report assembly
    - Implement `ReportBuilder` class with `build(metrics_rules, flags) -> ExecutionReport` method
    - Convert metrics rule instances into `MetricObservation` entries
    - Include inconsistency flags in the `flags` section
    - Set `schema_version` and `generator` fields
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

- [ ] 8. Implement ContractCompiler orchestrator
  - [ ] 8.1 Create `trajectory_eval/generator/contract_compiler.py` — top-level compiler
    - Implement `ContractCompiler` class with `__init__(config_path)` and `async compile(trajectory, embed_client) -> CompilerOutput`
    - Implement `CompilerOutput` dataclass with `contract` and `report` fields
    - Implement rule classification registry (`_CLASSIFICATION`) mapping rule classes to Contract_Rule or Metrics_Rule
    - Orchestrate: run HardRuleRunner → classify → emit contract rules → deduplicate → build contract + report
    - Implement fault tolerance: catch per-rule exceptions, log, and continue
    - Route metrics rules to ReportBuilder, contract rules to Emitter + Deduplicator
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.1, 4.2, 4.3, 4.4, 4.5, 14.1, 14.2, 14.3, 14.5_

  - [ ]* 8.2 Write property test for rule routing (Property 3)
    - **Property 3: Correct Rule Routing**
    - **Validates: Requirements 3.1–3.9, 4.1–4.5**

  - [ ]* 8.3 Write property test for both artifacts produced (Property 11)
    - **Property 11: Both Artifacts Produced**
    - **Validates: Requirements 13.1, 14.1**

  - [ ]* 8.4 Write property test for fault tolerance (Property 12)
    - **Property 12: Fault Tolerance**
    - **Validates: Requirements 14.5**

- [ ] 9. Update YAML config and HardRuleRunner
  - [ ] 9.1 Modify `trajectory_eval/generator/hard_rules_config.yaml` — update rule registry
    - Remove `tool_index` from `per_step_rules`
    - Move `tool_param_type` and `tool_param_count` to `trajectory_rules`
    - Add `powerful_couples` list
    - Add `confidence_threshold` setting (default 3)
    - _Requirements: 5.1, 9.6, 9.7, 14.4, 15.4_

  - [ ] 9.2 Modify `trajectory_eval/generator/rule_runner.py` — integrate trajectory-level rules
    - Remove ToolIndexRule from the registry
    - Add ToolParamTypeRule and ToolParamCountRule to trajectory-level dispatch
    - Pass `powerful_couples` and `confidence_threshold` config to ToolSequenceRule
    - _Requirements: 5.1, 14.4, 15.4_

  - [ ] 9.3 Modify `trajectory_eval/generator/hard_rules.py` — replace facade with new entry point
    - Delete `tool_call_rules` function entirely (not in use)
    - Add `compile_contract` facade function that delegates to `ContractCompiler`
    - _Requirements: 5.3, 15.4_

- [ ] 10. Implement serialization and parsing
  - [ ] 10.1 Add `parse_contract` helper and `ContractParseError`
    - Implement `parse_contract(json_str: str) -> BehaviorContract` that wraps `model_validate_json` and raises `ContractParseError` on invalid input
    - Ensure round-trip: `BehaviorContract.model_validate_json(contract.model_dump_json())` == original
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [ ]* 10.2 Write property test for serialization round-trip (Property 10)
    - **Property 10: Contract Serialization Round-Trip**
    - **Validates: Requirements 16.3**

  - [ ]* 10.3 Write property test for structural completeness (Property 1)
    - **Property 1: Compiled Rule Structural Completeness**
    - **Validates: Requirements 1.3, 1.4, 1.5, 1.7, 1.8**

- [ ] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Integration wiring and test setup
  - [ ] 12.1 Create `tests/test_contract_redesign/conftest.py` — shared Hypothesis strategies
    - Implement `compiled_rules` strategy for generating valid CompiledRule instances
    - Implement `identical_rule_group` strategy for dedup testing
    - Implement `trajectory` strategy for generating realistic Trajectory instances
    - Implement `hard_rule` strategies for each concrete rule type
    - _Requirements: 1.3, 6.1_

  - [ ]* 12.2 Write integration tests for full compiler pipeline
    - Test end-to-end: Trajectory → ContractCompiler.compile() → verify contract + report structure
    - Test empty trajectory produces valid empty artifacts
    - Test trajectory with only metrics rules produces empty contract, populated report
    - Test that `compile_contract` facade produces correct output
    - _Requirements: 14.1, 14.2, 14.3_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation language is Python with Pydantic models and Hypothesis for PBT
- All new modules go under `trajectory_eval/generator/` and `trajectory_eval/models/`
- Tests go under `tests/test_contract_redesign/`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1", "7.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1", "6.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "5.1", "6.2"] },
    { "id": 4, "tasks": ["5.2", "5.3", "9.1"] },
    { "id": 5, "tasks": ["9.2", "9.3"] },
    { "id": 6, "tasks": ["8.1", "10.1"] },
    { "id": 7, "tasks": ["8.2", "8.3", "8.4", "10.2", "10.3"] },
    { "id": 8, "tasks": ["12.1"] },
    { "id": 9, "tasks": ["12.2"] }
  ]
}
```
