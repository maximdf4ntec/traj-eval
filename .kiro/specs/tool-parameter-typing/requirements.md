# Requirements Document

## Introduction

This specification covers the introduction of structured type identification and parsing for tool input parameters, a new Tool/ToolParameter domain model replacing the loose dictionary representation on Step, and an OOP parser hierarchy that splits raw parameter values into typed subcomponents (code, paths, command-line arguments, JSON, etc.). The work brings input-parameter typing to parity with the existing output-type detection, introduces a dedicated command-line argument parser, and migrates the Step model from flat tool_name/tool_input/tool_output fields to a first-class Tool object.

## Glossary

- **Tool**: A Pydantic model representing a single tool invocation, encapsulating the tool name, a list of input ToolParameter instances, and a typed output representation.
- **ToolParameter**: A Pydantic model representing one top-level parameter of a tool invocation, containing the raw key-value pair, a detected ParameterType, and an optional list of parsed SubParameter instances produced by the appropriate parser.
- **SubParameter**: A Pydantic model representing one parsed component extracted from a ToolParameter value (e.g., a flag, a positional argument, or a file-text body within a command-line string).
- **ParameterType**: An enumeration of detectable content types for tool input parameter values (e.g., code, file_path, command_line, json, xml, number, plain_text).
- **ParameterParser**: The abstract base class for all OOP parsers that inspect a raw parameter value, detect whether it matches their type, and decompose it into SubParameter instances.
- **CommandLineParser**: A concrete ParameterParser that splits a single shell command string into subcomponents: the command name, positional arguments, flags, option-value pairs, file paths, inline content arguments, and simple redirections or pipe boundaries.
- **CodeParser**: A concrete ParameterParser that detects Python (or other language) source code and extracts structural subcomponents.
- **PathParser**: A concrete ParameterParser that detects file-system paths (Unix or Windows) and marks them accordingly.
- **JsonParser**: A concrete ParameterParser that detects valid JSON content and exposes its top-level structure as subcomponents.
- **Step**: The existing Pydantic model representing a single trajectory node; after this feature, Step.tool_name, Step.tool_input, and Step.tool_output fields are replaced by a single Tool field.
- **ParserRegistry**: The ordered collection of ParameterParser instances consulted to detect the type of a parameter value; each parser decides internally whether to recurse into nested content.
- **InputType**: A synonym for ParameterType used when referring specifically to input-parameter type detection (parallel to the existing OutputType enum for tool results).

## Requirements

### Requirement 1: Tool Model Introduction

**User Story:** As a rule author, I want tool invocations represented as a first-class object on Step, so that I can access structured input parameters and typed output through a consistent interface.

#### Acceptance Criteria

1. THE Tool SHALL contain a `name` field of type string identifying the invoked tool.
2. THE Tool SHALL contain an `inputs` field holding an ordered list of ToolParameter instances corresponding to the tool invocation arguments.
3. THE Tool SHALL contain an `output` field representing the raw tool result (string content, consistent with the existing tool_output semantics).
4. WHEN a Step has step_type `tool_call`, THE Step SHALL contain a non-None `tool` field of type Tool.
5. WHEN a Step has step_type other than `tool_call`, THE Step SHALL set the `tool` field to None.
6. THE Step SHALL NOT contain `tool_name`, `tool_input`, or `tool_output` as top-level fields after migration.

### Requirement 2: ToolParameter Model

**User Story:** As a rule author, I want each tool parameter modeled with its detected type and parsed subcomponents, so that I can write fine-grained validation rules against parameter structure.

#### Acceptance Criteria

1. THE ToolParameter SHALL contain a `key` field of type string holding the original parameter name.
2. THE ToolParameter SHALL contain a `raw_value` field of type Any preserving the original unmodified parameter value.
3. THE ToolParameter SHALL contain a `detected_type` field of type ParameterType reflecting the inferred content type of the raw value.
4. THE ToolParameter SHALL contain a `sub_parameters` field holding a list of SubParameter instances (empty list when no parsing applies).
5. WHEN the detected_type is `plain_text`, THE ToolParameter SHALL have an empty `sub_parameters` list.

### Requirement 3: SubParameter Model

**User Story:** As a rule author, I want parsed subcomponents accessible as structured objects, so that I can write assertions about individual parts of a complex parameter value.

#### Acceptance Criteria

1. THE SubParameter SHALL contain a `name` field of type string describing the subcomponent role (e.g., "command_name", "flag", "positional_arg", "file_path", "file_text").
2. THE SubParameter SHALL contain a `value` field of type Any holding the extracted subcomponent content.
3. THE SubParameter SHALL contain a `detected_type` field of type ParameterType indicating the type of the subcomponent content when further typing is applicable.
4. WHEN a ParameterParser recurses into nested content, THE SubParameter SHALL itself contain a `sub_parameters` list with deeper-level parsed results.
5. WHEN a ParameterParser does not recurse into the subcomponent, THE SubParameter SHALL have an empty `sub_parameters` list.

### Requirement 4: ParameterType Enumeration

**User Story:** As a developer, I want a comprehensive enumeration of input parameter content types, so that parsers and rules share a common vocabulary for type identification.

#### Acceptance Criteria

1. THE ParameterType enum SHALL include the value `code` for source code content.
2. THE ParameterType enum SHALL include the value `file_path` for file-system path content.
3. THE ParameterType enum SHALL include the value `command_line` for shell command strings.
4. THE ParameterType enum SHALL include the value `json` for valid JSON content.
5. THE ParameterType enum SHALL include the value `xml` for valid XML content.
6. THE ParameterType enum SHALL include the value `number` for numeric scalar values.
7. THE ParameterType enum SHALL include the value `plain_text` for unstructured text that matches no other type.
8. THE ParameterType enum SHALL be extensible by adding new values without breaking existing parsers or rules.

### Requirement 5: ParameterParser Abstract Base

**User Story:** As a developer, I want a uniform abstract interface for all parameter parsers, so that new content types can be added by implementing a single class without modifying existing code.

#### Acceptance Criteria

1. THE ParameterParser SHALL define an abstract method `can_parse(value: Any) -> bool` that returns True when the parser recognizes the value as its target type.
2. THE ParameterParser SHALL define an abstract method `parse(key: str, value: Any) -> ToolParameter` that decomposes the value into a ToolParameter with populated sub_parameters.
3. THE ParameterParser SHALL define a class-level `parameter_type` attribute identifying which ParameterType it handles.
4. WHEN `can_parse` returns False for a given value, THE ParserRegistry SHALL NOT invoke `parse` on that parser for that value.
5. THE ParameterParser subclass SHALL decide internally whether to recurse into nested content within subcomponents (parser-decides depth strategy).

### Requirement 6: CommandLineParser

**User Story:** As a rule author, I want command-line argument strings parsed into their constituent parts, so that I can validate individual flags, paths, and inline content within tool_input commands.

#### Acceptance Criteria

1. WHEN a parameter value is a string matching a shell command pattern, THE CommandLineParser `can_parse` method SHALL return True.
2. WHEN the CommandLineParser parses a command string, THE CommandLineParser SHALL extract a SubParameter with name `command_name` containing the base command or executable name.
3. WHEN the CommandLineParser parses a command string containing flags (e.g., `--verbose`, `-n`), THE CommandLineParser SHALL extract one SubParameter per flag with name `flag` and value set to the flag string.
4. WHEN the CommandLineParser parses a command string containing option-value pairs (e.g., `--file_text 'content'`), THE CommandLineParser SHALL extract a SubParameter with name matching the option key and value set to the option value.
5. WHEN the CommandLineParser parses a command string containing positional arguments that are file paths, THE CommandLineParser SHALL extract a SubParameter with name `file_path` and detected_type `file_path`.
6. WHEN the CommandLineParser encounters a pipe operator `|`, THE CommandLineParser SHALL treat it as a command boundary and parse each segment as a separate command subcomponent.
7. WHEN the CommandLineParser encounters an output redirection `>` or `>>`, THE CommandLineParser SHALL extract a SubParameter with name `redirection_target` containing the target path.
8. THE CommandLineParser SHALL handle quoted arguments (single quotes, double quotes) by preserving the content within quotes as a single value.

### Requirement 7: CodeParser

**User Story:** As a rule author, I want source code parameter values identified and optionally decomposed, so that rules can distinguish code parameters from plain text.

#### Acceptance Criteria

1. WHEN a parameter value is a string containing Python keywords and valid Python syntax, THE CodeParser `can_parse` method SHALL return True.
2. WHEN the CodeParser parses a code value, THE CodeParser SHALL produce a ToolParameter with detected_type `code`.
3. THE CodeParser SHALL apply the same Python-keyword heuristic used by the existing `_is_valid_python` function in tool_result_type.py.

### Requirement 8: PathParser

**User Story:** As a rule author, I want file-path parameter values identified structurally, so that I can validate path-related parameters independently of their context.

#### Acceptance Criteria

1. WHEN a parameter value is a string matching a Unix absolute path pattern (starts with `/`, contains path separators and an extension), THE PathParser `can_parse` method SHALL return True.
2. WHEN a parameter value is a string matching a Windows absolute path pattern (starts with a drive letter followed by `:\`), THE PathParser `can_parse` method SHALL return True.
3. WHEN the PathParser parses a path value, THE PathParser SHALL produce a ToolParameter with detected_type `file_path` and an empty sub_parameters list.

### Requirement 9: JsonParser

**User Story:** As a rule author, I want JSON-structured parameter values identified and their top-level keys exposed as subcomponents, so that rules can inspect JSON parameter structure.

#### Acceptance Criteria

1. WHEN a parameter value is a string containing valid JSON (object or array), THE JsonParser `can_parse` method SHALL return True.
2. WHEN the JsonParser parses a JSON object value, THE JsonParser SHALL extract one SubParameter per top-level key with name set to the key and value set to the corresponding JSON value.
3. WHEN the JsonParser parses a JSON array value, THE JsonParser SHALL produce a ToolParameter with detected_type `json` and sub_parameters containing one SubParameter per array element with name `element_{index}`.

### Requirement 10: ParserRegistry and Dispatch

**User Story:** As a developer, I want a registry that dispatches parameter values to the correct parser in priority order, so that type detection is deterministic and extensible.

#### Acceptance Criteria

1. THE ParserRegistry SHALL maintain an ordered list of ParameterParser instances consulted from first to last for each parameter value.
2. WHEN a parameter value matches multiple parsers via `can_parse`, THE ParserRegistry SHALL use the first matching parser in priority order.
3. WHEN no parser matches a parameter value, THE ParserRegistry SHALL produce a ToolParameter with detected_type `plain_text` and empty sub_parameters.
4. THE ParserRegistry SHALL allow insertion of new parsers at any position in the priority list without modifying existing parser implementations.
5. THE ParserRegistry default ordering SHALL be: CommandLineParser, JsonParser, CodeParser, PathParser (most specific to least specific for string values).

### Requirement 11: Step Model Migration

**User Story:** As a developer, I want a clean migration from the flat tool fields on Step to the new Tool object, so that all existing consumers are updated consistently.

#### Acceptance Criteria

1. WHEN a trajectory parser produces a Step with step_type `tool_call`, THE parser SHALL construct a Tool object from the tool_name and tool_input data and assign it to `step.tool`.
2. THE SWE-bench parser SHALL convert its `{"command": arguments_string}` tool_input format into a Tool with a single ToolParameter (key="command", raw_value=arguments_string) processed through the ParserRegistry.
3. WHEN an existing rule accesses tool parameters, THE rule SHALL read from `step.tool.inputs` instead of `step.tool_input`.
4. WHEN an existing rule accesses the tool name, THE rule SHALL read from `step.tool.name` instead of `step.tool_name`.
5. WHEN an existing rule accesses the tool output, THE rule SHALL read from `step.tool.output` instead of `step.tool_output`.
6. THE migration SHALL update ToolParamCountRule to count `step.tool.inputs` length.
7. THE migration SHALL update ToolParamTypeRule to read parameter types from ToolParameter.detected_type.

### Requirement 12: Input Type Detection Parity with Output

**User Story:** As a rule author, I want input parameter type detection to use the same detection strategies available for output type detection, so that the system has consistent typing across both directions.

#### Acceptance Criteria

1. THE ParameterParser hierarchy SHALL detect `json` content in input parameters using the same structural check as `_is_valid_json` in tool_result_type.py.
2. THE ParameterParser hierarchy SHALL detect `code` content in input parameters using the same Python-keyword heuristic as `_is_valid_python` in tool_result_type.py.
3. THE ParameterParser hierarchy SHALL detect `file_path` content in input parameters using path-pattern matching consistent with `_is_file_path_output` in tool_result_type.py.
4. THE ParameterParser hierarchy SHALL detect `xml` content in input parameters using the same structural check as `_is_valid_xml` in tool_result_type.py.
5. THE ParameterParser hierarchy SHALL detect `number` content in input parameters using the same check as `_is_number` in tool_result_type.py.

### Requirement 13: OOP Structure and Extensibility

**User Story:** As a developer, I want each parser implemented as a separate class following the one-class-per-variant pattern, so that the codebase remains modular and new types can be added without modifying existing classes.

#### Acceptance Criteria

1. THE ParameterParser base class SHALL be an abstract Pydantic BaseModel following the same ABC + BaseModel pattern used by the Rule hierarchy.
2. Each concrete parser (CommandLineParser, CodeParser, PathParser, JsonParser) SHALL be a separate class in its own module or a dedicated parsers subpackage.
3. THE concrete parsers SHALL NOT contain logic for detecting types outside their own responsibility.
4. WHEN a new parameter type is introduced, THE developer SHALL implement a single new ParameterParser subclass and register it in the ParserRegistry without modifying existing parser classes.
5. THE ParameterParser hierarchy SHALL follow the project convention of using Pydantic model_validator and field_validator for derived field computation.
