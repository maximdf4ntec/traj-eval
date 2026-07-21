# Implementation Plan: Type-Based Data Flow Rule

## Overview

Extend the existing `DataDependencyRule` class with a type-based heuristic pass that emits `potential`-confidence rules when tool_call input parameter types match earlier tool_result output types. The implementation adds a new `ConfidenceLevel.potential` enum value, defines an eligible-types constant, implements recursive type extraction helpers, and orchestrates the type-based pass within the existing `from_trajectory()` classmethod.

## Tasks

- [x] 1. Add ConfidenceLevel.potential enum value
  - [x] 1.1 Add `potential` value to the ConfidenceLevel enum in `trajectory_eval/models/rule.py`
    - Add `potential = "potential"` after the `low` value
    - Verify existing code is unaffected (no comparisons rely on enum ordering)
    - _Requirements: 1.1, 1.2_

- [x] 2. Define eligible types constant and type extraction helpers
  - [x] 2.1 Add `ELIGIBLE_TYPES` frozenset constant to `trajectory_eval/generator/rules/data_dependency.py`
    - Import `ParameterType` from `trajectory_eval.models.tool`
    - Define `ELIGIBLE_TYPES: frozenset[ParameterType]` containing `file_path`, `command_line`, `code`, `json`, `xml`, `url`, `yaml`, `date`
    - _Requirements: 2.1, 2.2_

  - [x] 2.2 Implement `_extract_types_from_param()` static method on `DataDependencyRule`
    - Accept a `ToolParameter | SubParameter` argument
    - Recursively traverse `sub_parameters` at arbitrary depth
    - Return `set[ParameterType]` containing only types in `ELIGIBLE_TYPES`
    - Base case: leaf node with no sub_parameters
    - _Requirements: 3.2, 4.2, 9.1_

  - [x] 2.3 Implement `_collect_type_sources()` classmethod on `DataDependencyRule`
    - Accept `steps: list[Step]` and `up_to_index: int`
    - Iterate tool_result steps with index < `up_to_index`
    - Skip steps where `tool.output_typed is None`
    - Call `_extract_types_from_param()` on each `output_typed`
    - Return `dict[ParameterType, list[tuple[str, int]]]` mapping type → list of (tool_name, step_index)
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 2.4 Write property tests for recursive type extraction (Property 3)
    - **Property 3: Recursive Depth Discovery**
    - **Validates: Requirements 3.2, 4.2, 9.1**

  - [ ]* 2.5 Write property test for eligible type filtering (Property 1)
    - **Property 1: Eligible Type Filtering**
    - **Validates: Requirements 2.1, 2.2**

- [x] 3. Implement type-based pass orchestrator
  - [x] 3.1 Define `TypeMatch` named tuple in `trajectory_eval/generator/rules/data_dependency.py`
    - Fields: `tool_name`, `param_key`, `source_tool_name`, `detected_type`
    - Used as deduplication key
    - _Requirements: 7.1, 7.2_

  - [x] 3.2 Implement `_type_based_rules()` classmethod on `DataDependencyRule`
    - Iterate tool_call steps in trajectory order
    - For each step, call `_collect_type_sources()` with preceding steps
    - Extract eligible types from each input parameter via `_extract_types_from_param()`
    - Match input types against type-sources
    - Apply self-referential exclusion (skip when tool_call tool name == source tool name)
    - Apply deduplication via `TypeMatch` seen-set
    - Emit `DataDependencyRule` with `confidence=ConfidenceLevel.potential`, `param_value=f"type:{detected_type.value}"`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 7.1, 7.2_

  - [ ]* 3.3 Write property test for self-referential exclusion (Property 5)
    - **Property 5: Self-Referential Exclusion**
    - **Validates: Requirements 6.1**

  - [ ]* 3.4 Write property test for deduplication invariant (Property 6)
    - **Property 6: Deduplication Invariant**
    - **Validates: Requirements 7.1, 7.2**

  - [ ]* 3.5 Write property test for type-based rule emission correctness (Property 4)
    - **Property 4: Type-Based Rule Emission Correctness**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**

- [x] 4. Integrate type-based pass into from_trajectory()
  - [x] 4.1 Modify `DataDependencyRule.from_trajectory()` to call `_type_based_rules()`
    - Execute existing value-based pass first (unchanged)
    - Call `_type_based_rules(trajectory)` after value-based pass
    - Concatenate results: `value_rules + type_rules`
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ]* 4.2 Write property test for type-source requires non-null output_typed (Property 2)
    - **Property 2: Type-Source Collection Requires Non-Null output_typed**
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [ ]* 4.3 Write property test for unified output completeness (Property 7)
    - **Property 7: Unified Output Completeness**
    - **Validates: Requirements 8.1, 8.2, 8.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Edge case unit tests and integration validation
  - [ ]* 6.1 Write unit tests for edge cases
    - Empty trajectory produces no type-based rules
    - All-excluded types (plain_text, number, boolean only) produce no rules
    - Deeply nested parameters (depth >= 3) are discovered
    - tool_result with `output_typed is None` produces no type-sources
    - _Requirements: 2.2, 3.1, 9.1_

  - [ ]* 6.2 Write integration test for combined value-based and type-based output
    - Create trajectory with steps that produce both value-based and type-based rules
    - Verify `from_trajectory()` returns both in correct order (value-based first)
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using Hypothesis
- Unit tests validate specific examples and edge cases
- The implementation language is Python, matching the existing codebase
- All new methods are added to the existing `DataDependencyRule` class in `trajectory_eval/generator/rules/data_dependency.py`
- The only model change is adding `potential` to `ConfidenceLevel` in `trajectory_eval/models/rule.py`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "3.1"] },
    { "id": 4, "tasks": ["3.2"] },
    { "id": 5, "tasks": ["3.3", "3.4", "3.5"] },
    { "id": 6, "tasks": ["4.1"] },
    { "id": 7, "tasks": ["4.2", "4.3"] },
    { "id": 8, "tasks": ["6.1", "6.2"] }
  ]
}
```
