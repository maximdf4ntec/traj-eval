# Requirements Document

## Introduction

The Trajectory Evaluation System is a tool for analyzing LLM agent execution traces (trajectories), automatically generating evaluation rules from them, and producing reusable test artifacts. A user loads a trajectory from Langfuse into a standalone web UI, the system generates node-level and global rules in plain English, the user reviews and approves or edits each rule, and the system then exports pytest code for hard rules and DeepEval YAML for soft rules. The resulting test suite can be run against future trajectory runs of the same agent as regression tests.

---

## Glossary

- **Trajectory**: A complete record of an agent execution, consisting of an ordered sequence of Steps plus global metadata.
- **Step**: A single node in a Trajectory, representing one interaction unit (e.g., an LLM prompt/response pair, a tool call, or a user message).
- **Step_Type**: The classification of a Step — one of: `user_message`, `llm_response`, `tool_call`, `tool_result`, `error`.
- **Rule**: A plain-English statement describing an expected property of a Step or a Trajectory, classified as Hard or Soft.
- **Hard_Rule**: A Rule that can be evaluated deterministically (e.g., equality check, string containment, numeric comparison). Exported as pytest code.
- **Soft_Rule**: A Rule that requires LLM-based judgment (e.g., quality of an explanation). Exported as DeepEval YAML.
- **Rule_Set**: The complete collection of Rules associated with a single Trajectory.
- **Approval**: A per-Rule user action that marks a Rule as accepted, rejected, or edited before export.
- **Rule_Store**: A persistent local storage (SQLite or JSON file) that holds approved Rule_Sets.
- **Trajectory_Loader**: The component that fetches a Trajectory from Langfuse and transforms it into the canonical Trajectory object.
- **Rule_Generator**: The component that analyzes a Trajectory and produces a Rule_Set.
- **Rule_Exporter**: The component that converts an approved Rule_Set into pytest files and DeepEval YAML files.
- **Web_UI**: The standalone web application through which the user loads trajectories, reviews rules, and triggers exports.
- **Langfuse**: The external LLM observability platform used as the trajectory source.
- **DeepEval**: The external LLM evaluation framework whose YAML format is used for Soft_Rule export.
- **Pseudocode**: A human-readable, language-agnostic expression of a Rule's logic, stored alongside the plain-English description and used as the basis for code generation.
- **Load_Result**: The structured object returned by the Trajectory_Loader, containing either a successfully parsed Trajectory plus a list of field-level warnings, or an error code and message on failure.
- **Trajectory_Parser_Registry**: The component that holds registered TrajectoryParser implementations and dispatches format detection and parsing for local trajectory files.
- **TrajectoryParser**: An interface with a `format_name` string, a `can_parse(raw_data) -> bool` method for format detection, and a `parse(raw_data) -> Load_Result` method for converting raw data into a canonical Trajectory; each file-format-specific parser implements this interface.
- **OpenAI_Messages_Format**: A JSON array of objects where each element contains at least a `role` field (string) and an optional `content` field, representing a conversation in OpenAI's chat completion messages format.
- **Rule_Confidence**: A categorical signal (`high`, `medium`, or `low`) assigned to every Rule at generation time, indicating how strongly the rule is grounded in observable, deterministic behaviour in the trajectory.
- **Anchor_Fact**: A short factual statement about a value in an `llm_response` step's response text, returned by the LLM as a candidate Hard_Rule during the existing soft-rule generation call, with a one-sentence justification explaining why a change to this value would indicate a regression.
- **Tool_Call_Appropriateness**: A Soft_Rule judgment that evaluates whether the tool selected with the given arguments was a reasonable choice given the preceding trajectory context, assessed on four criteria: tool-goal fit, argument grounding, non-redundancy, and ordering correctness.
- **Result_Plausibility**: A Soft_Rule judgment that evaluates whether a tool's output plausibly follows from the inputs provided to that tool call.
- **Tool_Context_Window**: The configurable number of preceding steps (default 3, env var `TOOL_CONTEXT_WINDOW`) included as context when generating the combined `tool_call_appropriateness` + `result_plausibility` LLM call for a `tool_result` step.

---

## Requirements

### Requirement 1: Canonical Trajectory Data Model

**User Story:** As a developer, I want a well-defined trajectory object, so that all system components operate on a consistent, complete data structure regardless of the source format.

#### Acceptance Criteria

1. THE Trajectory SHALL contain: a unique identifier (non-empty string), source platform name (non-empty string), agent name (string, nullable), start timestamp (ISO 8601 UTC datetime), end timestamp (ISO 8601 UTC datetime), total latency in milliseconds (non-negative integer), total token count (non-negative integer), total cost in USD (non-negative float), a list of Steps in execution order, and a metadata dictionary whose keys are strings and values are JSON-serializable primitives or objects.
2. THE Step SHALL contain: a zero-based index (non-negative integer), a Step_Type (one of `user_message`, `llm_response`, `tool_call`, `tool_result`, `error`), a timestamp (ISO 8601 UTC datetime), latency in milliseconds (non-negative integer), token count (non-negative integer), cost in USD (non-negative float), a prompt string (nullable for non-LLM steps), a response string (nullable for non-response steps), a tool name (nullable for non-tool steps), a tool input dictionary (nullable for non-tool steps; keys are strings and values are JSON-serializable), a tool output string (nullable for non-tool steps), an error message string (nullable for non-error steps), model name (nullable for non-LLM steps), temperature (nullable for non-LLM steps; when present, a float in the range [0.0, 2.0] inclusive), and a metadata dictionary whose keys are strings and values are JSON-serializable primitives or objects.
3. WHEN a Trajectory is loaded, THE system SHALL validate that Step timestamps are consistent with their sequence order; IF steps have timestamps that do not match their zero-based index ordering, THEN THE Trajectory_Loader SHALL either reorder the Steps by ascending timestamp or reject the Trajectory with an error message identifying the out-of-order steps, depending on a configurable behavior (default: reorder). WHEN steps are reordered, THE Trajectory_Loader SHALL re-assign their zero-based `index` fields sequentially (from 0 to N-1) to ensure the index matches their final position in the ordered list.
4. IF a required field is absent in the source data, THEN THE Trajectory_Loader SHALL populate that field with a typed null value, and THE Load_Result SHALL include a warning entry identifying the Step index (or `trajectory` for top-level fields) and the field name that was missing. IF other data quality issues are detected (e.g., out-of-range numeric values, malformed strings, or type mismatches for non-required fields), THEN THE Load_Result SHALL also include a warning entry identifying the affected field and a description of the issue.
5. THE Trajectory SHALL be serializable to and deserializable from JSON without data loss (round-trip property), as fully specified in Requirement 9.

---

### Requirement 2: Langfuse Trajectory Ingestion

**User Story:** As a user, I want to load a trajectory from Langfuse by providing a trace ID, so that I can analyze real agent executions without manual data preparation.

#### Acceptance Criteria

1. WHEN a user provides a trace ID that is a non-empty string of 1–200 characters in the Web_UI, THE Trajectory_Loader SHALL fetch the corresponding trace from the Langfuse API and return a Load_Result containing a canonical Trajectory object.
2. WHEN the Langfuse API returns observation records, THE Trajectory_Loader SHALL map each observation to one or more Steps using the following rules: observations of type `llm` map to a single Step of type `llm_response`; observations of type `tool` map to two consecutive Steps — a `tool_call` Step followed immediately by a `tool_result` Step, ordered by their start timestamps; observations of type `event` with `role == "user"` map to a Step of type `user_message`; observations of type `event` with any role other than `user` are silently skipped; observations with a non-null error field map to a Step of type `error` regardless of observation type; observations of unrecognized types are silently skipped and recorded as warnings in the Load_Result. This mapping logic applies to all observation types including any future additions.
3. IF the Langfuse API returns an authentication error, THEN THE Trajectory_Loader SHALL return a Load_Result with error message "Langfuse authentication failed. Check your API key and host configuration."
4. IF the Langfuse API returns a not-found error for the given trace ID, THEN THE Trajectory_Loader SHALL return a Load_Result with error message "Trace not found."
5. IF the Langfuse API does not respond within 10 seconds, THEN THE Trajectory_Loader SHALL return a Load_Result with error message "Langfuse connection timed out."
6. THE Trajectory_Loader SHALL be configurable with a Langfuse host URL via the environment variable `LANGFUSE_HOST`, a public key via `LANGFUSE_PUBLIC_KEY`, and a secret key via `LANGFUSE_SECRET_KEY` (which is required to retrieve traces), and SHALL use these values without requiring code changes.

---

### Requirement 3: Rule Generation — Node-Level Rules

**User Story:** As a user, I want the system to automatically generate candidate evaluation rules for each step in a trajectory, so that I do not have to write rules manually from scratch.

#### Acceptance Criteria

1. WHEN the Trajectory_Loader returns a valid Trajectory, THE Rule_Generator SHALL produce at least one candidate Rule for every Step in the Trajectory.
2. IF a Step has Step_Type `tool_call`, THEN THE Rule_Generator SHALL generate the following Hard_Rules: (a) tool name equality (`step[i].tool == "<observed_name>"`), (b) one key-presence check per key in the tool input dictionary (`"<key>" in step[i].tool_input`), and (c) one value check per key whose value is a string or numeric type (`step[i].tool_input["<key>"] == <observed_value>`).
3. IF a Step has Step_Type `llm_response`, THEN THE Rule_Generator SHALL, as part of the same LLM call used to generate the Soft_Rule description (per criterion 3.10), request that the LLM also return 0–3 "regression-sensitive Anchor_Facts" — factual statements of up to 200 characters each about values in the response that, if changed in a future run, would indicate a regression. Each Anchor_Fact SHALL include a one-sentence justification explaining why a change to that value would indicate a regression. Each returned Anchor_Fact SHALL be converted into a candidate Hard_Rule (ContainsCheck using case-sensitive substring match) with confidence `high` if the anchor value appears verbatim in a nearby tool step (per Requirement 14 criterion 2) or `medium` otherwise, and SHALL be presented in the review UI with its justification displayed as a tooltip or sub-label on the Rule card, defaulting to `pending` status. THE Rule_Generator SHALL NOT generate regex-based ContainsCheck Hard_Rules (named-entity, numeric-literal, or JSON-key token matching) for `llm_response` steps. IF the LLM call fails or times out (after 30 seconds), THEN THE Rule_Generator SHALL produce zero anchor-based Hard_Rules for that step (not a crash, not a placeholder) and SHALL record a warning in the Load_Result. The existing single Soft_Rule per `llm_response` Step (relevance-to-prompt, as described in criterion 3.10) is preserved.
4. IF a Step has Step_Type `tool_result`, THEN THE Rule_Generator SHALL generate Hard_Rules for: (a) one key-presence check per key in the tool output parsed as JSON (`"<key>" in step[i].tool_output_parsed`), and (b) one value-type check per key (`isinstance(step[i].tool_output_parsed["<key>"], <observed_type>)`). Additionally, THE Rule_Generator SHALL generate **two** Soft_Rules for the `tool_call` + `tool_result` pair using a single LLM call. The LLM call SHALL include: a **preceding context window** consisting of up to N steps immediately before the `tool_call` step (where N is configurable via environment variable `TOOL_CONTEXT_WINDOW`, default 3), represented as a structured summary of each step's type and — where present — the step's tool name, tool input argument keys, and tool output keys; the **tool name** and **tool input** (arguments) of the `tool_call` step; and the **tool output** of the `tool_result` step. The LLM call SHALL return a structured JSON response with two distinct judgment fields: (1) **`tool_call_appropriateness`** — a plain-English judgment of up to 300 characters evaluating whether selecting this tool with these arguments was a reasonable choice given the preceding context, assessed on four criteria: (a) Tool-goal fit: is this tool suited to the current sub-goal evident from context? (b) Argument grounding: are the arguments grounded in information actually available at this point in the trajectory, not fabricated or hallucinated? (c) Non-redundancy: does this call re-fetch or repeat something already established earlier in the trajectory without justification? (d) Ordering correctness: does the call respect obvious operation ordering (e.g., not deleting before verifying, not writing before reading)? (2) **`result_plausibility`** — a plain-English judgment of up to 300 characters evaluating whether the tool result plausibly follows from the tool input provided. Each judgment SHALL become a separate Soft_Rule with `scope = step` pointing to the `tool_result` step index, `confidence = medium`, and the LLM-produced text as the plain-English description. IF the LLM call fails, times out (after 30 seconds), or returns a response that is not valid JSON, THEN THE Rule_Generator SHALL fall back to two templated descriptions: `tool_call_appropriateness` fallback: "The tool call at step [i-1] was an appropriate choice given the preceding context."; `result_plausibility` fallback: "The tool result at step [i] is a plausible response to the tool input provided at the preceding tool_call step." The `tool_call_appropriateness` Soft_Rule SHALL be generated only WHEN the `tool_result` step has a preceding `tool_call` step (i.e., `step_index > 0` and the preceding step has type `tool_call`). IF no preceding `tool_call` step exists, THEN THE Rule_Generator SHALL generate only the `result_plausibility` Soft_Rule for that `tool_result` step.
5. IF a Step has Step_Type `user_message`, THEN THE Rule_Generator SHALL generate one Hard_Rule: `len(step[i].prompt) > 0`.
6. IF a Step has Step_Type `error`, THEN THE Rule_Generator SHALL generate two Hard_Rules: (a) `len(step[i].error_message) > 0`, and (b) `step[i].index == <observed_index>`.
7. THE Rule_Generator SHALL assign each Rule a unique identifier within the Rule_Set using the format `<step_type>_<step_index>_<sequence_number>` for step-scoped rules (e.g., `tool_call_2_1`).
8. THE Rule_Generator SHALL generate both a plain-English description and a Pseudocode expression for every Rule.
9. WHEN a Rule can be fully expressed using the pattern-matching logic defined in criteria 2–6, THE Rule_Generator SHALL produce that Rule without invoking an LLM.
10. WHEN generating Soft_Rules per criteria 3 and 4, THE Rule_Generator SHALL invoke an LLM to produce the plain-English description. IF the LLM call fails or times out, THEN THE Rule_Generator SHALL fall back to the templated descriptions defined in criteria 3 and 4 and record a warning in the Load_Result.

---

### Requirement 4: Rule Generation — Global Rules

**User Story:** As a user, I want rules that apply to the trajectory as a whole, so that I can enforce end-to-end constraints beyond individual steps.

#### Acceptance Criteria

1. WHEN a Trajectory is loaded, THE Rule_Generator SHALL produce the following global Hard_Rules:
   - `len(trajectory.steps) <= len(trajectory.steps) * (1 + tolerance_margin)` and `len(trajectory.steps) >= len(trajectory.steps) * (1 - tolerance_margin)`, where `tolerance_margin` defaults to 0.2 and is configurable via environment variable `RULE_TOLERANCE_MARGIN`.
   - For each distinct Step_Type observed in the loaded Trajectory: `any(s.step_type == "<type>" for s in trajectory.steps)`.
   - `trajectory.total_cost_usd <= <observed_cost> * (1 + tolerance_margin)` and `trajectory.total_cost_usd >= <observed_cost> * (1 - tolerance_margin)`.
   - `trajectory.total_latency_ms <= <observed_latency> * (1 + tolerance_margin)` and `trajectory.total_latency_ms >= <observed_latency> * (1 - tolerance_margin)`.
2. WHEN a Trajectory is loaded, THE Rule_Generator SHALL produce the following global Soft_Rules:
   - "The final `llm_response` step's response text addresses the topic and intent of the first `user_message` step's prompt text."
   - "No two consecutive steps in the trajectory share the same Step_Type and identical content fields (prompt, response, tool_name, tool_input, tool_output, error_message)."
3. THE Rule_Generator SHALL label each global Rule with scope `global` and each node-level Rule with scope `step` plus the corresponding zero-based step index.

---

### Requirement 5: Rule Review and Approval in the Web UI

**User Story:** As a user, I want to review, approve, reject, or edit each generated rule before exporting, so that I have full control over the test suite that gets generated.

#### Acceptance Criteria

1. THE Web_UI SHALL display the loaded Trajectory as a structured step-by-step list view, and SHALL display the generated Rule_Set in a separate panel on the same screen.
2. THE Web_UI SHALL display each Rule with: its plain-English description, its Pseudocode expression, its type (Hard or Soft), its scope (global or step index), and its current approval status (pending, approved, rejected).
3. WHEN a user clicks "Approve" on a Rule, THE Web_UI SHALL set that Rule's status to `approved`, regardless of its current status.
4. WHEN a user clicks "Reject" on a Rule, THE Web_UI SHALL set that Rule's status to `rejected`, regardless of its current status.
5. WHEN a user activates edit mode on a Rule, modifies the plain-English description or Pseudocode, and clicks "Save", THE Web_UI SHALL update the Rule in memory with the new values and set its status to `pending`. IF the user activates edit mode and clicks "Cancel" without saving, THE Web_UI SHALL discard the edits and leave the Rule's description, Pseudocode, and status unchanged.
6. THE Web_UI SHALL provide an "Approve All" button that sets all Rules with status `pending` to `approved`. Rules with status `rejected` SHALL NOT be changed by this action.
7. WHEN a user clicks "Export", THE Web_UI SHALL pass only Rules with status `approved` to the Rule_Exporter.
8. THE Web_UI SHALL display a live count of approved, rejected, and pending Rules, updated immediately after each status change.
9. WHEN a user clicks "Export" and zero Rules have status `approved`, THE Web_UI SHALL display the message "No approved rules to export." and SHALL NOT invoke the Rule_Exporter.

---

### Requirement 6: Rule Persistence

**User Story:** As a user, I want approved rule sets to be saved locally, so that they persist across sessions and can be retrieved for later export or reference.

#### Acceptance Criteria

1. WHEN a user triggers export or activates the explicit "Save" action in the Web_UI, THE Rule_Store SHALL persist all Rules with status `approved` in the current Rule_Set, along with the Trajectory identifier, agent name (or an empty string if not provided), and an ISO 8601 UTC save timestamp.
2. THE Rule_Store SHALL use a local SQLite database as the storage backend when the environment variable `RULE_STORE_BACKEND` is set to `sqlite` (the default), and a JSON file when set to `json`. The SQLite file path and JSON file path SHALL each be configurable via separate environment variables (`RULE_STORE_SQLITE_PATH` and `RULE_STORE_JSON_PATH`).
3. WHEN the Rule_Store is queried with a Trajectory identifier that exists in the store, THE Rule_Store SHALL return the most recently saved Rule_Set for that identifier, ordered by save timestamp descending.
4. WHEN the Rule_Store is queried with a Trajectory identifier that does not exist in the store, THE Rule_Store SHALL return an empty result and SHALL surface the message "No saved rule set found for this trajectory." to the Web_UI.
5. THE Rule_Store SHALL support listing all saved Rule_Sets, returning for each entry: the Trajectory identifier, agent name, and save timestamp.
6. IF a save operation fails due to a disk or permission error, THEN THE Rule_Store SHALL leave previously saved data unchanged and SHALL surface a message to the Web_UI stating the save failed and the reason (e.g., "Save failed: permission denied on <path>").

---

### Requirement 7: pytest Export for Hard Rules

**User Story:** As a developer, I want hard rules exported as pytest code, so that I can run them as regression tests against future trajectory runs.

#### Acceptance Criteria

1. WHEN a user explicitly requests export for a Rule_Set containing at least one approved Hard_Rule, THE Rule_Exporter SHALL generate a file named `test_hardcoded_rules.py` containing one test function per approved Hard_Rule.
2. THE Rule_Exporter SHALL name each test function `test_step_{index}_{rule_id}` for step-scoped rules and `test_global_{rule_id}` for global rules, where `rule_id` is the Rule_Generator-assigned identifier with any non-alphanumeric characters replaced by underscores.
3. THE Rule_Exporter SHALL generate pytest code that accepts a `trajectory` fixture as input to each test function, so that the same test file can be run against any Trajectory instance.
4. THE Rule_Exporter SHALL translate each Rule's Pseudocode expression to a syntactically valid Python `assert` statement.
5. THE Rule_Exporter SHALL include the plain-English Rule description as a docstring immediately inside each test function, before the `assert` statement.
6. IF a Pseudocode expression cannot be translated to valid Python, THEN THE Rule_Exporter SHALL emit a commented-out placeholder with the message `# TODO: manual implementation required — {plain_english_description}` in place of the `assert` statement, and SHALL surface a warning message to the Web_UI identifying the rule by its identifier.
7. THE Rule_Exporter SHALL generate a `conftest.py` file that defines a `trajectory` fixture. The fixture SHALL load a Trajectory from a JSON file whose path is provided via the pytest command-line option `--trajectory-path`.
8. WHEN a user explicitly requests export and no approved Hard_Rules exist in the Rule_Set, THEN THE Rule_Exporter SHALL NOT generate `test_hardcoded_rules.py` and SHALL notify the Web_UI with the message "No approved hard rules to export."
9. WHEN exporting, THE Rule_Exporter SHALL overwrite any existing files of the same name in the output directory, and SHALL preserve other unrelated files in that directory.
10. THE Rule_Exporter SHALL generate a `README.md` file in the export output directory containing instructions on how to install required testing dependencies (pytest) and how to run the exported tests.

---

### Requirement 8: DeepEval YAML Export for Soft Rules

**User Story:** As a developer, I want soft rules exported as DeepEval YAML, so that I can run LLM-based evaluations against future trajectory runs using a standard framework.

#### Acceptance Criteria

1. WHEN a user triggers export for a Rule_Set containing at least one approved Soft_Rule, THE Rule_Exporter SHALL generate a YAML file named `soft_rule_evals.yaml`. The file SHALL be a valid YAML document containing a top-level mapping with at least one of the keys `step_evaluations` or `global_evaluations`, each holding a sequence of test case entries. Each entry SHALL contain the keys `name`, `criteria`, `input`, and `actual_output`.
2. THE Rule_Exporter SHALL set each Soft_Rule entry's fields as follows: `name` is set to the Rule's unique identifier; `criteria` is set to the Rule's plain-English description; `input` is set to the literal string value of the relevant Step's `prompt` field (for step-scoped rules) or the first `user_message` Step's `prompt` field (for global rules); `actual_output` is set to the literal string value of the relevant Step's `response` field (for step-scoped rules) or the final `llm_response` Step's `response` field (for global rules). IF the relevant `prompt` or `response` field is null, THEN the corresponding YAML field SHALL be set to the empty string `""`.
3. THE Rule_Exporter SHALL place step-scoped Soft_Rule entries under the key `step_evaluations` and global Soft_Rule entries under the key `global_evaluations`.
4. THE Rule_Exporter SHALL include the Rule's Pseudocode expression as a YAML line comment (prefixed with `#`) on the line immediately preceding each entry's `name` field.
5. IF a user explicitly requests export and no approved Soft_Rules exist in the Rule_Set, THEN THE Rule_Exporter SHALL NOT generate `soft_rule_evals.yaml` and SHALL notify the Web_UI with the message "No approved soft rules to export." IF approved Soft_Rules exist and file generation fails for any other reason (e.g., disk error, permission error, or YAML serialization failure), THEN THE Rule_Exporter SHALL surface an appropriate error notification to the Web_UI that identifies the failure reason. WHEN exporting, THE Rule_Exporter SHALL overwrite any existing files of the same name in the output directory.

---

### Requirement 9: Trajectory Serialization Round-Trip

**User Story:** As a developer, I want the trajectory model to serialize and deserialize correctly, so that saved trajectories and test fixtures are reliable.

#### Acceptance Criteria

1. THE Trajectory SHALL serialize to a JSON string without raising an error, given a Trajectory instance where all required fields defined in Requirement 1 criterion 1 are present and non-null, and all nullable fields are either null or of their specified types.
2. WHEN a JSON string produced by serializing a Trajectory is deserialized, THE resulting Trajectory SHALL be field-by-field equal to the original, including all nested Step fields, with numeric values equal to their JSON-serialized precision (no floating-point rounding beyond what JSON encoding introduces).
3. WHEN a JSON string produced by serializing a Trajectory is deserialized and then serialized again, THE second JSON string SHALL be byte-for-byte identical to the first. This property requires that object keys are serialized in a deterministic order (e.g., sorted alphabetically) on every serialization call.
4. IF a JSON string is missing one or more required Trajectory fields (as defined in Requirement 1 criterion 1), THEN THE deserializer SHALL raise a validation error whose message explicitly names every missing required field.
5. IF a JSON string contains a field whose value is of a type that does not match the type specified in Requirement 1 criteria 1 and 2, THEN THE deserializer SHALL raise a validation error whose message identifies the field name and the expected type.

---

### Requirement 10: Web UI — Trajectory Loading Flow

**User Story:** As a user, I want a simple, guided interface for loading a trajectory and triggering rule generation, so that I can go from a trace ID to a reviewable rule set in minimal steps.

#### Acceptance Criteria

1. THE Web_UI SHALL present a form on the home screen containing: a text input field labelled "Trace ID" that accepts strings of 1–200 characters, and an optional text input field labelled "Agent Name".
2. WHEN a user submits the form with a non-empty Trace ID, THE Web_UI SHALL display a loading indicator.
3. WHILE the Trajectory_Loader is fetching and the Rule_Generator is processing, THE Web_UI SHALL keep the loading indicator visible and SHALL disable the submit button.
4. WHEN loading and rule generation complete successfully, THE Web_UI SHALL automatically navigate to the rule review screen without requiring an additional user action, and SHALL hide the loading indicator.
5. WHEN the Trajectory_Loader returns an error, THE Web_UI SHALL hide the loading indicator, re-enable the submit button, and display the error message returned by the Trajectory_Loader in a visible error area on the home screen, allowing the user to correct the Trace ID and resubmit.
6. THE Web_UI SHALL display a summary bar on the rule review screen showing: total step count (integer), total token count (integer), total cost in USD (float formatted to 6 decimal places), and total latency in milliseconds (integer).

---

### Requirement 11: Local File Trajectory Loading

**User Story:** As a user, I want to load a trajectory from a local JSON file, so that I can analyze agent executions stored on disk without requiring a Langfuse connection.

#### Acceptance Criteria

1. THE Web_UI SHALL present a file-loading option (file picker or file path input field) on the home screen in addition to the existing Langfuse Trace ID form, allowing the user to choose between loading from Langfuse or loading from a local file. THE Web_UI SHALL accept files up to 50 MB in size; IF a selected file exceeds 50 MB, THE Web_UI SHALL display a validation error without submitting the file to the backend.
2. WHEN a user submits a non-empty file selection or file path, THE Web_UI SHALL display a loading indicator and disable the submit control (consistent with the Langfuse loading flow in Requirement 10 criteria 2–3). THE Trajectory_Loader SHALL then read the file contents and invoke the Trajectory_Parser_Registry to detect the file format and dispatch parsing to the appropriate TrajectoryParser implementation.
3. THE Trajectory_Loader SHALL return a Load_Result for local file loading that has the same structure as the Load_Result returned for Langfuse loading: a successfully parsed Trajectory plus a list of warnings on success, or an error code and error message on failure.
4. IF the specified file does not exist on disk, THEN THE Trajectory_Loader SHALL return a Load_Result with error message "File not found: <file_path>".
5. IF the file exists but cannot be read (e.g., due to a permission error or I/O failure), THEN THE Trajectory_Loader SHALL return a Load_Result with error message "File could not be read: <reason>".
6. IF the Trajectory_Parser_Registry finds no matching parser for the file contents, THEN THE Trajectory_Loader SHALL return a Load_Result with error message "Unrecognized trajectory format."
7. IF a matching TrajectoryParser is found but the file contents are malformed or fail validation, THEN THE Trajectory_Loader SHALL return a Load_Result with an error message that identifies the format name and describes the specific parse failure.
8. THE Trajectory_Loader SHALL NOT require the environment variable `TRAJECTORY_FILE_FORMATS` or any equivalent configuration variable to be set in order to use built-in file format parsers; built-in parsers SHALL be available at all times.
9. WHEN local file loading and rule generation complete successfully, THE Web_UI SHALL automatically navigate to the rule review screen and hide the loading indicator, identical to the success behavior defined in Requirement 10 criterion 4.
10. WHEN the Trajectory_Loader returns an error for a local file load, THE Web_UI SHALL hide the loading indicator, re-enable the submit control, and display the error message in a visible error area on the home screen, allowing the user to correct the file selection and resubmit. IF the user submits the file-load form without selecting a file or entering a file path, THE Web_UI SHALL display an inline validation message and SHALL NOT invoke the Trajectory_Loader.

---

### Requirement 12: Extensible Trajectory Parser Registry

**User Story:** As a developer, I want a pluggable parser registry so that new trajectory file formats can be added without modifying existing code.

#### Acceptance Criteria

1. THE Trajectory_Parser_Registry SHALL maintain an ordered list of registered TrajectoryParser implementations, where each TrajectoryParser exposes: a `format_name` string identifying the format, a `can_parse(raw_data) -> bool` method that returns True when the raw data matches the expected format, and a `parse(raw_data) -> Load_Result` method that converts the raw data into a Load_Result containing a canonical Trajectory.
2. WHEN the Trajectory_Parser_Registry receives raw file data, THE Trajectory_Parser_Registry SHALL invoke `can_parse()` on each registered TrajectoryParser in registration order and SHALL use the first TrajectoryParser whose `can_parse()` returns True to perform parsing. IF a TrajectoryParser's `can_parse()` raises an exception, THE Trajectory_Parser_Registry SHALL treat that invocation as returning False and SHALL continue to the next registered TrajectoryParser without propagating the exception.
3. IF no registered TrajectoryParser returns True from `can_parse()` for the given raw data, THEN THE Trajectory_Parser_Registry SHALL return a Load_Result with error message "Unrecognized trajectory format."
4. WHEN the application starts, THE Trajectory_Parser_Registry SHALL automatically register all built-in TrajectoryParser implementations without requiring any user or operator configuration.
5. THE Trajectory_Parser_Registry SHALL expose a programmatic registration method that allows third-party TrajectoryParser implementations to be registered at runtime, so that new file formats can be added without modifying existing Trajectory_Parser_Registry or TrajectoryParser source code. WHEN a TrajectoryParser is registered via this method, it SHALL be appended after all currently registered parsers. IF a TrajectoryParser with the same `format_name` as an already-registered parser is submitted, THE registration method SHALL replace the existing entry in-place (preserving its position in the ordered list) rather than appending a duplicate.
6. THE Trajectory_Loader SHALL delegate all local file format detection and parsing to the Trajectory_Parser_Registry, and SHALL NOT contain format-specific parsing logic directly.

---

### Requirement 13: OpenAI Messages Format Parser

**User Story:** As a user, I want to load trajectories saved in OpenAI-style messages format (a JSON array with role/content objects), so that I can evaluate agent conversations stored in that common format.

#### Acceptance Criteria

1. WHEN the Trajectory_Parser_Registry invokes `can_parse()` on the OpenAI Messages Format parser, THE parser SHALL return True if and only if the raw data is a JSON array where every element is an object containing at least a `role` field whose value is a string. IF the raw data is a valid JSON array with zero elements, THE parser SHALL return True (an empty messages array is vacuously valid) and `parse()` SHALL produce a Trajectory with an empty Steps list.
2. WHEN the OpenAI Messages Format parser parses a valid messages array, THE parser SHALL apply the following mapping rules to convert each element to a Step:
   - Elements with `role == "system"` SHALL be silently skipped and SHALL NOT produce a Step.
   - Elements with `role == "user"` SHALL produce a Step of type `user_message`; the element's `content` field SHALL be mapped to the Step's `prompt` field. IF the `content` field is absent or null, the Step's `prompt` field SHALL be set to null.
   - Elements with `role == "assistant"` SHALL be mapped as follows:
     - IF `tool_calls` is present and is a non-empty list:
       - IF `content` is also present and non-null, it SHALL first produce a Step of type `llm_response`; the `content` field SHALL be mapped to the Step's `response` field.
       - THEN it SHALL produce a Step of type `tool_call` for each item in the `tool_calls` list: the item's `function.name` SHALL be mapped to the Step's `tool_name`, and `function.arguments` (parsed as a JSON object) SHALL be mapped to the Step's `tool_input`.
     - ELSE (if `tool_calls` is absent or empty):
       - It SHALL produce a single Step of type `llm_response`; the element's `content` field SHALL be mapped to the Step's `response` field. IF the `content` field is absent or null, the Step's `response` field SHALL be set to null.
   - Elements with `role == "tool"` SHALL produce a Step of type `tool_result`; the element's `content` field SHALL be mapped to the Step's `tool_output` field. IF the `content` field is absent or null, the Step's `tool_output` field SHALL be set to null.
   - Elements with any role value not listed above SHALL be silently skipped and SHALL NOT produce a Step.
3. WHEN the OpenAI Messages Format parser skips an element due to an unrecognized role value, THE parser SHALL record a warning entry in the Load_Result identifying the element's index and role value (e.g., "Skipped element at index 3: unrecognized role 'function'").
4. WHEN the OpenAI Messages Format parser assigns timestamps to the generated Steps, THE parser SHALL assign synthetic monotonically-increasing timestamps using the formula Unix epoch (1970-01-01T00:00:00Z) + step_index seconds (where step_index is the zero-based index of the Step within the resulting Steps list), and SHALL set `latency_ms`, `token_count`, and `cost_usd` to 0 for every Step, because messages-format files do not contain timing or cost data. THE Trajectory's `start_time` SHALL be set to the timestamp of the first Step (Unix epoch + 0 seconds) and `end_time` SHALL be set to the timestamp of the last Step; IF the Steps list is empty, both `start_time` and `end_time` SHALL be set to Unix epoch.
5. WHEN the OpenAI Messages Format parser constructs the Trajectory, THE parser SHALL derive the Trajectory `id` from the source file name by stripping the last file extension only (e.g., `"conversation.json"` → `"conversation"`, `"run.v2.json"` → `"run.v2"`), and SHALL set `source_platform` to the string `"openai_messages"`.
6. IF the raw data is a valid JSON array but one or more elements are missing the `role` field or the `role` field is not a string, THEN THE OpenAI Messages Format parser SHALL return a Load_Result with an error message identifying the index of the first non-conforming element and describing the violation.

---

### Requirement 14: Rule Confidence

**User Story:** As a user, I want each generated rule to carry a confidence score, so that I can quickly focus my review on high-signal rules and filter out low-confidence noise.

#### Acceptance Criteria

1. THE Rule_Generator SHALL assign a `confidence` field to every Rule at rule creation time. The `confidence` field SHALL carry one of three values: `high`, `medium`, or `low`. THE `confidence` field SHALL NOT be modifiable by the user.
2. THE Rule_Generator SHALL assign confidence levels according to the following scheme:
   - `tool_call` Hard_Rules: `high` (directly observed deterministic behaviour).
   - `tool_result` Hard_Rules (key-presence and type checks): `high`.
   - `llm_response` LLM-curated anchor Hard_Rules where the anchor value also appears as a case-sensitive substring in the `tool_input` or `tool_output` of a `tool_call` or `tool_result` Step within a configurable window (default 2 steps before or after, configurable via environment variable `RULE_ANCHOR_WINDOW`): `high`.
   - `llm_response` LLM-curated anchor Hard_Rules where the anchor value does NOT appear as a case-sensitive substring in any Step within the anchor window: `medium`.
   - `llm_response` Soft_Rules (relevance-to-prompt): `medium`.
   - `tool_result` Soft_Rules (`tool_call_appropriateness` and `result_plausibility`): `medium`.
   - `user_message` Hard_Rules (`len > 0`): `low`.
   - `error` Hard_Rules: `low`.
   - Global Hard_Rules (step-count, cost, latency bounds, step-type presence): `medium`.
   - Global Soft_Rules: `low`.
3. THE Web_UI SHALL display each Rule's confidence as a badge on the Rule card alongside the existing type, scope, and status badges.
4. THE Web_UI SHALL provide a confidence filter control on the rule review panel that allows the user to show or hide Rules by confidence level. The filter SHALL support three independent toggles: "High", "Medium", and "Low". All three toggles SHALL be enabled by default. WHEN a confidence level is toggled off, THE Web_UI SHALL hide all Rules with that confidence level from the rule list; WHEN a confidence level is toggled on again, THE Web_UI SHALL restore all previously hidden Rules with that confidence level to the rule list. Rules hidden by the confidence filter SHALL NOT be deleted and SHALL NOT have their status changed. The filter state is in-memory and SHALL reset to all toggles enabled on page reload.
5. IF a Rule is an LLM-curated anchor Hard_Rule (from Requirement 3 criterion 3), THEN THE Web_UI SHALL display that Rule's LLM-provided justification as a sub-label or tooltip on the Rule card. IF no justification is present (e.g., for non-LLM-curated rules), the justification display area SHALL be absent from the Rule card.
6. WHEN a user clicks "Approve All", THE Web_UI SHALL apply the action only to Rules that are currently visible (i.e., not hidden by the confidence filter) and have status `pending`. Rules hidden by the confidence filter SHALL NOT have their status changed by the "Approve All" action.


#### Open questions / comments
1. New hard rules: 
    a. Trajectory Edit Distance
    b. Tool Invocation Redundancy Ratio $$\text{Redundancy Rate} = \frac{\text{Duplicate Tool Calls}}{\text{Total Tool Calls}}$$
    c. Tool sequence "Tool B cannot be called unless Tool A was successfully executed first"
    d. Step-to-Step Data Dependency (Lineage Validation) - assert that a variable used in Step $N$ was born in the observation of Step $N-1$ (or earlier).
    e. Multi-Turn Cycle Breaker - This assertion ensures that the agent does not repeat identical behaviors within a short cognitive horizon.
    f. Token-to-Step Efficiency Ceiling - This catches prompt injection or context stuffing where the agent's thought blocks grow exponentially longer each turn.
    g. Environment Mutation Matcher - If a tool observation explicitly reports a failure or an empty state, the agent's subsequent choices must adapt. (def test_empty_observation_handling(trajectory):
    for i, step in enumerate(trajectory[:-1]):
        if "error" in str(step['observation']).lower() or "not found" in str(step['observation']).lower():
            next_step = trajectory[i+1]
            # The agent must pivot to error handling, not try to continue reading
            assert next_step['action'] != step['action'], f"Agent ignored error state in step {i} and retried blindly.")
    h. Tools parameters (count and type)
    i. Tool index in trajectory (as today)

2. Rename Rule type "Hard" -> "Assertion", "Soft" -> "Eval"
3. Split between succeesful trajectories and failed ones
4. Support for "golden path"
5. Guardrail Evasion - future
6. Support for hierarchical trajectories - future.
7. Automatic trajectory mutations - future.
8. Semantic Anchor Grounding - LLM-as-a-Judge Eval. Your compiler extracts the intent of the user's prompt (e.g., "Summarize risks") and maps it to the tools used, generating a dynamic rubric for an LLM Judge, rather than a hardcoded string match. 
9. Support langfuse trajectory evaluation and langfuse datasets (https://langfuse.com/guides/cookbook/example_pydantic_ai_mcp_agent_evaluation)
10. In addition to tests, provide trajectory analysis - spot errors, loops, ...
11. How to run a YAML file on a right trajectory - future
12. Tools result injection - future
13. Test set completeness verification procedure - future
14. Ask generalization questions (i.e. what is expected result of this tool, or is this tool necessary)
15. 
