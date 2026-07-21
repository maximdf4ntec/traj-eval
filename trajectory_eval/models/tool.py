"""Tool, ToolParameter, SubParameter, and ParameterType models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, model_validator


class ParameterType(str, Enum):
    """Enumeration of detectable content types for tool input parameter values.

    Extensible by adding new values without breaking existing parsers or rules,
    since parsers only match on their own type and ignore unknown variants.
    """

    code = "code"
    file_path = "file_path"
    command_line = "command_line"
    json = "json"
    xml = "xml"
    number = "number"
    url = "url"
    yaml = "yaml"
    # TODO make sure all parsers are implemented
    date = "date"
    boolean = "boolean"
    plain_text = "plain_text"


class SubParameter(BaseModel):
    """A parsed component extracted from a ToolParameter value.

    Attributes:
        name: Role label describing the subcomponent (e.g. "command_name",
              "flag", "positional_arg", "file_path", "file_text").
        value: The extracted subcomponent content.
        detected_type: The inferred content type of this subcomponent.
        sub_parameters: Recursively nested subcomponents when a parser
                        recurses into nested content.
    """

    name: str
    value: Any
    detected_type: ParameterType = ParameterType.plain_text
    sub_parameters: list[SubParameter] = []


class ToolParameter(BaseModel):
    """One top-level parameter of a tool invocation.

    Attributes:
        key: The original parameter name (e.g. "command", "file_text").
        raw_value: The original unmodified parameter value.
        detected_type: The inferred content type of the raw value.
        sub_parameters: Parsed subcomponents produced by the appropriate parser.
                        Empty when detected_type is plain_text.
        direction: Whether this parameter is an input or output of the tool.
    """

    key: str
    raw_value: Any
    detected_type: ParameterType = ParameterType.plain_text
    sub_parameters: list[SubParameter] = []
    direction: Literal["input", "output"] = "input"

    @model_validator(mode="after")
    def _plain_text_has_no_sub_parameters(self) -> ToolParameter:
        """Enforce: when detected_type is plain_text, sub_parameters must be empty."""
        if self.detected_type == ParameterType.plain_text and self.sub_parameters:
            raise ValueError(
                "sub_parameters must be empty when detected_type is plain_text"
            )
        return self


class Tool(BaseModel):
    """A first-class representation of a single tool invocation.

    Attributes:
        name: The name of the invoked tool.
        inputs: Ordered list of ToolParameter instances corresponding to the
                tool invocation arguments.
        output: Raw tool result string (consistent with existing tool_output
                semantics). None when output is not yet available.
        output_typed: Typed representation of the tool output as a ToolParameter
                      with direction="output". None when output is not yet available
                      or has not been type-detected.
    """

    name: str
    inputs: list[ToolParameter] = []
    output: Optional[str] = None
    output_typed: Optional[ToolParameter] = None
