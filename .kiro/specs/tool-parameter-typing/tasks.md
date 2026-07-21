# Implementation Plan: Tool Parameter Typing

## Overview

Introduces structured type detection for tool input parameters via a new `Tool` model on `Step`, a `ParameterType` enum, `ToolParameter`/`SubParameter` data models, and an OOP parser hierarchy (`ParameterParser` ABC with `CommandLineParser`, `JsonParser`, `CodeParser`, `PathParser`) dispatched through a `ParserRegistry`. Migrates `Step` from flat `tool_name`/`tool_input`/`tool_output` fields to a single `tool: Optional[Tool]` field, and updates downstream consumers.

## Tasks

- [x] 1. Create data models (`models/tool.py`)
  - [x] 1.1 Create `ParameterType` enum and `SubParameter`, `ToolParameter`, `Tool` Pydantic models
    - Create `trajectory_eval/models/tool.py`
    - Define `ParameterType(str, Enum)` with values: `code`, `file_path`, `command_line`, `json`, `xml`, `number`, `plain_text`
    - Define `SubParameter(BaseModel)` with fields: `name: str`, `value: Any`, `detected_type: ParameterType`, `sub_parameters: list[SubParameter]`
    - Define `ToolParameter(BaseModel)` with fields: `key: str`, `raw_value: Any`, `detected_type: ParameterType`, `sub_parameters: list[SubParameter]`
    - Define `Tool(BaseModel)` with fields: `name: str`, `inputs: list[ToolParameter]`, `output: Optional[str]`
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1–4.8_

  - [x]* 1.2 Write unit tests for data models
    - Test `ParameterType` enum membership and string coercion
    - Test `SubParameter` recursive nesting
    - Test `ToolParameter` with `detected_type=plain_text` enforces empty `sub_parameters`
    - Test `Tool` construction with valid inputs and output
    - _Requirements: 2.5, 4.1–4.7_

- [x] 2. Create parser base and registry (`parsers/parameter/`)
  - [x] 2.1 Create `ParameterParser` ABC in `parsers/parameter/base.py`
    - Create `trajectory_eval/parsers/parameter/__init__.py`
    - Create `trajectory_eval/parsers/parameter/base.py`
    - Define `ParameterParser(BaseModel, ABC)` with `parameter_type` class attribute, abstract `can_parse(value: Any) -> bool`, abstract `parse(key: str, value: Any) -> ToolParameter`
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 13.1_

  - [x] 2.2 Create `ParserRegistry` in `parsers/parameter/registry.py`
    - Create `trajectory_eval/parsers/parameter/registry.py`
    - Implement ordered-priority dispatch: iterate parsers, first `can_parse` match wins
    - Implement `_detect_non_string` helper for int/float/list/dict → `number` or `plain_text`
    - Fallback to `ToolParameter(detected_type=plain_text, sub_parameters=[])` when no parser matches
    - Implement `insert(index, parser)` for extensibility
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x]* 2.3 Write property test for registry first-match determinism
    - **Property 5: Registry first-match determinism**
    - **Validates: Requirements 10.2**

  - [x]* 2.4 Write property test for registry fallback to plain_text
    - **Property 6: Registry fallback to plain_text**
    - **Validates: Requirements 10.3**

- [x] 3. Implement `PathParser` (`parsers/parameter/path.py`)
  - [x] 3.1 Create `PathParser` class
    - Create `trajectory_eval/parsers/parameter/path.py`
    - `can_parse`: detect Unix absolute paths (`/foo/bar.ext`) and Windows paths (`C:\...`)
    - `parse`: return `ToolParameter(detected_type=file_path, sub_parameters=[])`
    - Reuse detection logic consistent with `_is_file_path_output` from `tool_result_type.py`
    - _Requirements: 8.1, 8.2, 8.3, 12.3_

  - [x]* 3.2 Write unit tests for `PathParser`
    - Test Unix absolute paths, Windows paths, relative paths (should not match)
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 4. Implement `JsonParser` (`parsers/parameter/json_parser.py`)
  - [x] 4.1 Create `JsonParser` class
    - Create `trajectory_eval/parsers/parameter/json_parser.py`
    - `can_parse`: detect valid JSON strings (reuse `_is_valid_json` logic from `tool_result_type.py`)
    - `parse` for JSON objects: one `SubParameter` per top-level key (name=key, value=val)
    - `parse` for JSON arrays: one `SubParameter` per element with name `element_{i}`
    - _Requirements: 9.1, 9.2, 9.3, 12.1_

  - [x]* 4.2 Write property test for JsonParser key-count invariant
    - **Property 8: JsonParser key-count invariant**
    - **Validates: Requirements 9.2**

- [x] 5. Implement `CodeParser` (`parsers/parameter/code.py`)
  - [x] 5.1 Create `CodeParser` class
    - Create `trajectory_eval/parsers/parameter/code.py`
    - `can_parse`: reuse `_is_valid_python` heuristic from `tool_result_type.py`
    - `parse`: return `ToolParameter(detected_type=code)` with single SubParameter containing code body
    - _Requirements: 7.1, 7.2, 7.3, 12.2_

  - [x]* 5.2 Write unit tests for `CodeParser`
    - Test detection of Python source with keywords
    - Test non-code strings are rejected
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 6. Implement `CommandLineParser` (`parsers/parameter/command_line.py`)
  - [x] 6.1 Create `CommandLineParser` class
    - Create `trajectory_eval/parsers/parameter/command_line.py`
    - `can_parse`: detect shell command patterns (leading word, common tool names, flags)
    - `parse`: split into SubParameters: `command_name`, `flag`, `positional_arg`, `file_path`, option-value pairs, `redirection_target`
    - Handle pipe `|` as command boundary (parse each segment)
    - Handle `>` / `>>` redirection
    - Preserve quoted arguments (single/double quotes) as single unsplit tokens
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x]* 6.2 Write property test for CommandLineParser command_name extraction
    - **Property 7: CommandLineParser always extracts command_name**
    - **Validates: Requirements 6.2**

  - [x]* 6.3 Write property test for quoted argument preservation
    - **Property 10: Quoted argument preservation in CommandLineParser**
    - **Validates: Requirements 6.8**

- [x] 7. Checkpoint — Parsers complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Wire registry default order and export public API
  - [x] 8.1 Configure default parser ordering in `ParserRegistry._default_order` and update `__init__.py` exports
    - Default order: `CommandLineParser`, `JsonParser`, `CodeParser`, `PathParser`
    - Export `ParserRegistry`, `ParameterParser`, and all concrete parsers from `parsers/parameter/__init__.py`
    - _Requirements: 10.5, 13.2, 13.4_

  - [x]* 8.2 Write property test for detection parity with output-type detectors
    - **Property 9: Detection parity with output-type detectors**
    - **Validates: Requirements 12.1, 12.2, 12.3**

- [x] 9. Migrate `Step` model
  - [x] 9.1 Replace `tool_name`, `tool_input`, `tool_output` on `Step` with `tool: Optional[Tool]`
    - Add `from trajectory_eval.models.tool import Tool` import
    - Add field `tool: Optional[Tool] = None`
    - Remove `tool_name`, `tool_input`, `tool_output` fields
    - _Requirements: 1.4, 1.5, 1.6, 11.1_

  - [x]* 9.2 Write property tests for Tool presence/absence invariant
    - **Property 1: Tool presence invariant on tool_call steps**
    - **Property 2: Tool absence on non-tool_call steps**
    - **Validates: Requirements 1.4, 1.5**

- [x] 10. Update `parsers/swe_bench.py` to construct `Tool` objects
  - [x] 10.1 Modify `parse_swe_bench` to build `Tool` via `ParserRegistry`
    - Instantiate `ParserRegistry` at module level or inside function
    - In `tool_call` branch: construct `tool_input_dict = {"command": tc["arguments"]}`, detect via registry, create `Tool(name=tc["tool_name"], inputs=[...], output=None)`
    - In `tool_result` branch: attach output to the previous tool_call step's `tool.output`
    - Pass `tool=tool_obj` to Step constructor (remove `tool_name`, `tool_input`, `tool_output` args)
    - _Requirements: 11.1, 11.2_

  - [x]* 10.2 Write property test for raw value preservation
    - **Property 3: Raw value preservation**
    - **Validates: Requirements 2.2**

  - [x]* 10.3 Write property test for plain-text implies no sub_parameters
    - **Property 4: Plain-text implies no sub_parameters**
    - **Validates: Requirements 2.5, 3.5**

- [x] 11. Migrate `generator/rules/tool_checks.py`
  - [x] 11.1 Update `ToolParamCountRule` and `ToolParamTypeRule` to use `step.tool`
    - `ToolParamCountRule.from_trajectory`: change `step.tool_input` → `step.tool.inputs`, `step.tool_name` → `step.tool.name`
    - `ToolParamCountRule.generate`: update pseudocode to `len(step[i].tool.inputs)`
    - `ToolParamTypeRule.from_trajectory`: iterate `step.tool.inputs` for ToolParameter objects, use `param.detected_type` instead of `type(val).__name__`
    - `ToolParamTypeRule.generate`: update pseudocode reference
    - _Requirements: 11.3, 11.4, 11.5, 11.6, 11.7_

  - [x]* 11.2 Write unit tests for migrated rule classes
    - Test `ToolParamCountRule.from_trajectory` produces correct counts from `step.tool.inputs`
    - Test `ToolParamTypeRule.from_trajectory` reads `detected_type` from ToolParameter
    - _Requirements: 11.6, 11.7_

- [x] 12. Final checkpoint — Full integration
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses Python throughout; no language selection needed

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2"] },
    { "id": 2, "tasks": ["3.1", "4.1", "5.1", "6.1"] },
    { "id": 3, "tasks": ["2.3", "2.4", "3.2", "4.2", "5.2", "6.2", "6.3"] },
    { "id": 4, "tasks": ["8.1"] },
    { "id": 5, "tasks": ["8.2", "9.1"] },
    { "id": 6, "tasks": ["9.2", "10.1"] },
    { "id": 7, "tasks": ["10.2", "10.3", "11.1"] },
    { "id": 8, "tasks": ["11.2"] }
  ]
}
```
