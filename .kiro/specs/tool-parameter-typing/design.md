# Design: Tool Parameter Typing

## Overview

Introduces structured type detection and parsing for tool input parameters, a first-class `Tool` model on `Step`, and an OOP parser hierarchy that decomposes raw parameter values into typed subcomponents. Mirrors the existing output-type detection (`OutputType` / `ToolResultTypeRule`) but for the input side.

## Architecture

```
trajectory_eval/
├── models/
│   ├── trajectory.py          # Step, Trajectory (modified: +tool field, -tool_name/input/output)
│   ├── tool.py                # NEW: Tool, ToolParameter, SubParameter, ParameterType
│   └── rule.py                # unchanged
├── parsers/
│   ├── swe_bench.py           # modified: constructs Tool objects
│   └── parameter/             # NEW subpackage
│       ├── __init__.py        # exports ParserRegistry, ParameterParser
│       ├── base.py            # ParameterParser ABC
│       ├── registry.py        # ParserRegistry (ordered dispatch)
│       ├── command_line.py    # CommandLineParser
│       ├── json_parser.py     # JsonParser
│       ├── code.py            # CodeParser
│       └── path.py            # PathParser
└── generator/rules/
    ├── tool_checks.py         # modified: reads step.tool.inputs
    └── tool_result_type.py    # unchanged (output side)
```

## Data Models

### ParameterType (Enum)

```python
# trajectory_eval/models/tool.py
from enum import Enum

class ParameterType(str, Enum):
    code = "code"
    file_path = "file_path"
    command_line = "command_line"
    json = "json"
    xml = "xml"
    number = "number"
    plain_text = "plain_text"
```

### SubParameter

```python
class SubParameter(BaseModel):
    name: str                              # role label: "command_name", "flag", "file_path", etc.
    value: Any                             # extracted content
    detected_type: ParameterType = ParameterType.plain_text
    sub_parameters: list["SubParameter"] = []
```

### ToolParameter

```python
class ToolParameter(BaseModel):
    key: str                               # original param name (e.g. "command", "file_text")
    raw_value: Any                         # unmodified original value
    detected_type: ParameterType = ParameterType.plain_text
    sub_parameters: list[SubParameter] = []
```

### Tool

```python
class Tool(BaseModel):
    name: str
    inputs: list[ToolParameter] = []
    output: Optional[str] = None
```

### Step Migration

```python
class Step(BaseModel):
    # ... existing fields ...
    tool: Optional[Tool] = None            # NEW — replaces tool_name, tool_input, tool_output
    # tool_name, tool_input, tool_output removed
```

## Parser Hierarchy

### ParameterParser (ABC)

```python
# trajectory_eval/parsers/parameter/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class ParameterParser(BaseModel, ABC):
    """Abstract base following the same ABC + BaseModel pattern as Rule."""
    parameter_type: ParameterType  # class-level identifier

    @abstractmethod
    def can_parse(self, value: Any) -> bool: ...

    @abstractmethod
    def parse(self, key: str, value: Any) -> ToolParameter: ...
```

### Concrete Parsers

| Class | Module | Detects | SubParameters Produced |
|-------|--------|---------|----------------------|
| `CommandLineParser` | `command_line.py` | Shell commands (leading word + flags/paths) | `command_name`, `flag`, `positional_arg`, `file_path`, `redirection_target`, option-value pairs |
| `JsonParser` | `json_parser.py` | Valid JSON strings | One per top-level key (objects) or `element_{i}` (arrays) |
| `CodeParser` | `code.py` | Python source (keyword heuristic from `_is_valid_python`) | Single subparam with the code body; detected_type=code |
| `PathParser` | `path.py` | Unix/Windows absolute paths | Empty sub_parameters; detected_type=file_path |

Detection reuses the existing helpers from `tool_result_type.py`:
- `_is_valid_json` → `JsonParser.can_parse`
- `_is_valid_python` → `CodeParser.can_parse`
- `_is_file_path_output` → `PathParser.can_parse`
- `_is_valid_xml` → future `XmlParser.can_parse`
- `_is_number` → handled inline by registry fallback

### ParserRegistry

```python
# trajectory_eval/parsers/parameter/registry.py
class ParserRegistry:
    """Ordered-priority dispatch. First parser whose can_parse returns True wins."""

    def __init__(self, parsers: list[ParameterParser] | None = None):
        self._parsers = parsers or self._default_order()

    @staticmethod
    def _default_order() -> list[ParameterParser]:
        return [CommandLineParser(), JsonParser(), CodeParser(), PathParser()]

    def detect(self, key: str, value: Any) -> ToolParameter:
        """Dispatch value to the first matching parser, or return plain_text."""
        if not isinstance(value, str):
            # Non-string values: number check, else plain_text
            return ToolParameter(key=key, raw_value=value,
                                 detected_type=_detect_non_string(value))
        for parser in self._parsers:
            if parser.can_parse(value):
                return parser.parse(key, value)
        return ToolParameter(key=key, raw_value=value,
                             detected_type=ParameterType.plain_text)

    def insert(self, index: int, parser: ParameterParser) -> None:
        self._parsers.insert(index, parser)
```

## SWE-bench Parser Integration

The `parse_swe_bench` function constructs `Tool` objects during step creation:

```python
registry = ParserRegistry()

# Inside the tool_call branch:
tool_input_dict = {"command": tc["arguments"]}
inputs = [registry.detect(k, v) for k, v in tool_input_dict.items()]
tool = Tool(name=tc["tool_name"], inputs=inputs)
step = Step(..., tool=tool)
```

## Rule Migration

`ToolParamCountRule` and `ToolParamTypeRule` change field access:

```python
# Before:
len(step.tool_input)
step.tool_name
type(step.tool_input[key])

# After:
len(step.tool.inputs)
step.tool.name
step.tool.inputs[i].detected_type
```

## Error Handling

- Non-string values (int, list, dict) → `ParameterType.number` or `plain_text` (no parser invoked).
- Parser exceptions (malformed JSON, broken syntax) → catch internally, fall through to next parser.
- `None` tool_input on a `tool_call` step → `Tool(name=..., inputs=[], output=None)`.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Tool presence invariant on tool_call steps

*For any* Step with `step_type == tool_call`, the `tool` field SHALL be non-None and the `tool.name` field SHALL be a non-empty string.

**Validates: Requirements 1.4, 1.1**

### Property 2: Tool absence on non-tool_call steps

*For any* Step with `step_type != tool_call`, the `tool` field SHALL be None.

**Validates: Requirements 1.5**

### Property 3: Raw value preservation

*For any* arbitrary value passed as a tool parameter, constructing a ToolParameter via the ParserRegistry SHALL preserve the original value in `raw_value` unchanged (identity).

**Validates: Requirements 2.2**

### Property 4: Plain-text implies no sub_parameters

*For any* ToolParameter whose `detected_type` is `plain_text`, the `sub_parameters` list SHALL be empty.

**Validates: Requirements 2.5, 3.5**

### Property 5: Registry first-match determinism

*For any* parameter value that is recognized by multiple parsers, the ParserRegistry SHALL produce a ToolParameter whose `detected_type` matches the `parameter_type` of the first matching parser in priority order.

**Validates: Requirements 10.2**

### Property 6: Registry fallback to plain_text

*For any* string value where no registered parser's `can_parse` returns True, the ParserRegistry SHALL produce a ToolParameter with `detected_type == plain_text` and an empty `sub_parameters` list.

**Validates: Requirements 10.3**

### Property 7: CommandLineParser always extracts command_name

*For any* string where `CommandLineParser.can_parse` returns True, the parsed result SHALL contain at least one SubParameter with `name == "command_name"`.

**Validates: Requirements 6.2**

### Property 8: JsonParser key-count invariant

*For any* valid JSON object string, the number of SubParameters produced by `JsonParser.parse` SHALL equal the number of top-level keys in the parsed JSON.

**Validates: Requirements 9.2**

### Property 9: Detection parity with output-type detectors

*For any* string value, if the existing `_is_valid_json` / `_is_valid_python` / `_is_file_path_output` helper returns True, then the corresponding ParameterParser's `can_parse` SHALL also return True for that same value.

**Validates: Requirements 12.1, 12.2, 12.3**

### Property 10: Quoted argument preservation in CommandLineParser

*For any* command string containing a quoted substring (single or double quotes), the CommandLineParser SHALL produce a SubParameter whose value contains the inner content of the quotes as a single unsplit token.

**Validates: Requirements 6.8**
