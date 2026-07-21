# Requirements Document

## Introduction

This feature extends the existing `DataDependencyRule` generator to emit additional "potential" confidence rules based on detected parameter types. When a tool_call input parameter shares a `detected_type` with an earlier tool_result's `output_typed` sub-parameter tree, the system infers a potential data-flow relationship even without exact value matching. This complements the existing value-based lineage detection with a type-based heuristic pass, unified within the same `from_trajectory()` classmethod.

## Glossary

- **DataDependencyRule**: The existing `HardRule` subclass in `trajectory_eval/generator/rules/data_dependency.py` that generates step-to-step lineage assertions.
- **ConfidenceLevel**: The enum in `trajectory_eval/models/rule.py` representing rule confidence (`high`, `medium`, `low`, and the new `potential`).
- **ToolParameter**: A Pydantic model representing a top-level tool parameter with `key`, `raw_value`, `detected_type`, `sub_parameters`, and `direction` fields.
- **SubParameter**: A recursive Pydantic model representing a parsed component with `name`, `value`, `detected_type`, and `sub_parameters` fields.
- **ParameterType**: The enum defining detectable content types (`file_path`, `command_line`, `code`, `json`, `xml`, `url`, `yaml`, `date`, `number`, `boolean`, `plain_text`).
- **Eligible_Type**: A ParameterType value eligible for type-based matching: `file_path`, `command_line`, `code`, `json`, `xml`, `url`, `yaml`, `date`. Excludes `plain_text`, `number`, and `boolean`.
- **output_typed**: The `Optional[ToolParameter]` field on `Tool` representing the typed representation of a tool's output.
- **Type_Match**: A tuple `(tool_name, param_key, source_tool_name, detected_type)` representing a unique type-based data flow connection.
- **Trajectory**: The top-level model containing an ordered list of Steps.
- **Step**: A single node in a trajectory with `index`, `step_type`, and `tool` fields.

## Requirements

### Requirement 1: New Confidence Level

**User Story:** As a rule consumer, I want a `potential` confidence level so that type-based inferences are clearly distinguished from value-based lineage.

#### Acceptance Criteria

1. THE ConfidenceLevel enum SHALL include a `potential` value.
2. WHEN ConfidenceLevel values are ordered by strength, THE ConfidenceLevel enum SHALL rank `potential` below `low` (ordering: `high` > `medium` > `low` > `potential`).

### Requirement 2: Eligible Type Filtering

**User Story:** As a rule generator, I want only semantically meaningful types considered for type-based matching so that trivial types do not produce false-positive rules.

#### Acceptance Criteria

1. THE DataDependencyRule type-based pass SHALL only match on ParameterType values in the set: `file_path`, `command_line`, `code`, `json`, `xml`, `url`, `yaml`, `date`.
2. THE DataDependencyRule type-based pass SHALL exclude `plain_text`, `number`, and `boolean` from type-based matching.

### Requirement 3: Output Type Extraction

**User Story:** As a rule generator, I want to collect typed parameters from tool_result outputs so that they can serve as type-based data sources.

#### Acceptance Criteria

1. THE DataDependencyRule type-based pass SHALL only process tool_result Steps whose `tool.output_typed` field is non-null.
2. WHEN a tool_result Step has a non-null `output_typed`, THE DataDependencyRule type-based pass SHALL recursively traverse the `output_typed` ToolParameter and all nested `sub_parameters` at all depths.
3. WHEN a SubParameter or ToolParameter encountered during traversal has a `detected_type` that is an Eligible_Type, THE DataDependencyRule type-based pass SHALL record the `detected_type` and the associated tool name as a type-source.

### Requirement 4: Input Type Extraction

**User Story:** As a rule generator, I want to collect typed parameters from tool_call inputs so that they can be matched against earlier type-sources.

#### Acceptance Criteria

1. THE DataDependencyRule type-based pass SHALL process all `tool.inputs` ToolParameter instances on tool_call Steps.
2. WHEN a tool_call Step is processed, THE DataDependencyRule type-based pass SHALL recursively traverse each input ToolParameter and all nested `sub_parameters` at all depths.
3. WHEN a SubParameter or ToolParameter encountered during input traversal has a `detected_type` that is an Eligible_Type, THE DataDependencyRule type-based pass SHALL attempt to match the `detected_type` against previously recorded type-sources.

### Requirement 5: Type-Based Rule Emission

**User Story:** As a rule generator, I want to emit a DataDependencyRule when a tool_call input type matches an earlier tool_result output type so that potential data flows are captured.

#### Acceptance Criteria

1. WHEN a tool_call input parameter's `detected_type` matches a previously recorded type-source `detected_type`, THE DataDependencyRule type-based pass SHALL emit a DataDependencyRule linking the tool_call step to the source tool_result step.
2. THE emitted DataDependencyRule SHALL have `confidence` set to `ConfidenceLevel.potential`.
3. THE emitted DataDependencyRule SHALL populate `param_key` with the key of the matched input ToolParameter.
4. THE emitted DataDependencyRule SHALL populate `source_tool_name` with the name of the tool that produced the matching output type.
5. THE emitted DataDependencyRule SHALL populate `source_step` with the step index of the tool_result that produced the matching output type.

### Requirement 6: Self-Referential Exclusion

**User Story:** As a rule consumer, I want type-based rules to exclude matches where a tool references its own output type so that trivial self-references are not reported.

#### Acceptance Criteria

1. WHEN the tool_call tool name equals the source tool_result tool name, THE DataDependencyRule type-based pass SHALL skip the match and not emit a rule.

### Requirement 7: Deduplication

**User Story:** As a rule consumer, I want at most one type-based rule per unique combination of tool, parameter key, source tool, and detected type so that duplicate rules are not emitted.

#### Acceptance Criteria

1. THE DataDependencyRule type-based pass SHALL deduplicate emitted rules on the tuple `(tool_name, param_key, source_tool_name, detected_type)`.
2. WHEN a duplicate Type_Match tuple is encountered, THE DataDependencyRule type-based pass SHALL skip the duplicate and not emit a rule.

### Requirement 8: Unified Integration

**User Story:** As a maintainer, I want type-based rule generation integrated into the existing `from_trajectory()` classmethod so that a single invocation produces both value-based and type-based rules.

#### Acceptance Criteria

1. WHEN `DataDependencyRule.from_trajectory()` is called, THE DataDependencyRule class SHALL execute both the existing value-based lineage pass and the type-based pass.
2. THE DataDependencyRule class SHALL return a single combined list containing rules from both passes.
3. THE type-based pass SHALL process steps in trajectory order (ascending step index).

### Requirement 9: Recursive Depth

**User Story:** As a rule generator, I want sub-parameter traversal to recurse to arbitrary depth so that deeply nested typed values are discovered.

#### Acceptance Criteria

1. WHEN traversing `sub_parameters` for type extraction, THE DataDependencyRule type-based pass SHALL recurse into all `sub_parameters` lists at every nesting level until no further `sub_parameters` exist.
