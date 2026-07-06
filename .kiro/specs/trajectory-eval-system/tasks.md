# Implementation Plan: Trajectory Evaluation System

## Overview

Implement a full-stack web application that ingests LLM-agent execution traces from Langfuse, auto-generates evaluation rules, lets users review and approve them, and exports the approved rules as pytest files and DeepEval YAML. The backend is a Python 3.11+ FastAPI service; the frontend is a React + TypeScript SPA built with Vite.

---

## Tasks

- [ ] 1. Project scaffold and shared configuration
  - [ ] 1.1 Create backend project structure
    - Initialize Python package layout: `trajectory_eval/` with sub-packages `models/`, `loader/`, `generator/`, `store/`, `exporter/`, `api/`, `llm/`
    - Add `__init__.py` to every package; define `__all__` in `trajectory_eval/__init__.py` exporting public types (`Trajectory`, `Step`, `Rule`, `RuleSet`, `LoadResult`, `ExportResult`)
    - Create `pyproject.toml` (or `requirements.txt`) pinning: `fastapi`, `uvicorn`, `pydantic>=2`, `langfuse`, `openai`, `aiosqlite`, `aiofiles`, `hypothesis`, `pytest`, `pytest-asyncio`, `pyyaml`, `httpx`
    - Create `.env.example` with `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `OPENAI_API_KEY`, `SOFT_RULE_LLM_MODEL`, `RULE_STORE_BACKEND`, `RULE_STORE_SQLITE_PATH`, `RULE_STORE_JSON_PATH`, `RULE_TOLERANCE_MARGIN`, `EXPORT_OUTPUT_DIR`
    - Create `pytest.ini` (or `pyproject.toml` section) with `asyncio_mode = auto`
    - _Requirements: 2.6, 6.2_

  - [ ] 1.2 Create frontend project structure
    - Scaffold Vite + React + TypeScript project under `frontend/`
    - Add dependencies: `react-query` (TanStack Query v5), `axios` (or `fetch`), `vitest`, `@testing-library/react`, `@testing-library/user-event`
    - Configure Vanilla CSS and Vite proxy to backend at `http://localhost:8000`
    - _Requirements: 5.1, 10.1_

- [ ] 2. Core data models
  - [ ] 2.1 Implement `Trajectory`, `Step`, and related Pydantic v2 models
    - Define `StepType`, `Step`, `Trajectory` in `trajectory_eval/models/trajectory.py`
    - Enforce all field constraints from Requirements 1.1 and 1.2: non-negative integers, non-empty strings, temperature range `[0.0, 2.0]`, `index >= 0`
    - Add `model_config = ConfigDict(frozen=True)` and custom validators for `temperature` and non-empty `id`/`source_platform`
    - Implement a `tool_output_parsed` computed property on `Step` that parses `tool_output` string as JSON (or returns None if empty/invalid) to prevent attribute errors during evaluation
    - Implement `Trajectory.model_serializer` with `round_trip=True` and sorted keys to satisfy deterministic JSON output
    - _Requirements: 1.1, 1.2, 9.1, 9.2, 9.3_

  - [ ]* 2.2 Write property tests for Trajectory serialization (P1, P2, P10)
    - Create `tests/test_serialization.py`; add Hypothesis composite strategies `trajectory_strategy()` and `step_strategy()` in `tests/conftest.py`
    - **Property 1: Trajectory serialization round-trip** — serialize then deserialize; assert field-by-field equality
    - **Property 2: Deterministic JSON serialization** — serialize twice; assert byte-for-byte identical strings
    - **Property 10: Missing required fields produce validation errors** — drop each required field; assert `ValidationError` names the missing field
    - `settings(max_examples=100)` on each test
    - **Validates: Requirements 1.5, 9.1, 9.2, 9.3, 9.4**

  - [ ] 2.3 Implement `Rule`, `RuleSet`, `LoadResult`, `ExportResult`, and `PseudocodeExpression` models
    - Define `PseudocodeExpression` discriminated union in `trajectory_eval/models/expressions.py`: variants `EqualityCheck`, `KeyPresenceCheck`, `ContainsCheck`, `LenGtZeroCheck`, `TypeCheck`, `BoundsCheck`, `StepTypePresenceCheck` — each with a `kind: Literal[...]` discriminator field
    - Implement `expression_to_pseudocode(expr: PseudocodeExpression) -> str` as a pure function in the same module, rendering each variant to a human-readable string
    - Define `RuleType`, `RuleScope`, `ApprovalStatus`, `Rule`, `RuleSet`, `WarningEntry`, `LoadResult`, `ExportResult` in `trajectory_eval/models/rules.py`
    - `Rule` must include `expression: PseudocodeExpression | None` and `pseudocode: str`; enforce that `pseudocode` is always set to `expression_to_pseudocode(expression)` when `expression` is not `None`
    - Ensure `Rule.id` format is validated by regex `^(user_message|llm_response|tool_call|tool_result|error)_\d+_\d+$|^global_\d+$`
    - Add `RuleConfidence` enum to `trajectory_eval/models/rules.py`: `high`, `medium`, `low`
    - Add `confidence: RuleConfidence` field to `Rule` (required, set at generation time, not user-editable)
    - Add `justification: str | None = None` field to `Rule` (non-null only for LLM-curated anchor Hard_Rules from `LLMResponseRuleGenerator`)
    - Export `RuleConfidence` from `trajectory_eval/models/__init__.py`
    - Add `RULE_ANCHOR_WINDOW` to `.env.example` (default `2`)
    - Export all expression types from `trajectory_eval/models/__init__.py`
    - _Requirements: 3.7, 3.8, 6.1, 7.1, 14.1_

- [ ] 3. Trajectory loader
  - [ ] 3.1 Implement `TrajectoryLoader`
    - Create `trajectory_eval/loader/trajectory_loader.py`
    - Validate `trace_id` length (1–200 characters); raise `ValueError` for invalid input
    - Initialize Langfuse client from `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` env vars
    - Implement `async def load(self, trace_id: str) -> LoadResult`; wrap sync Langfuse SDK calls with `asyncio.to_thread` if the SDK does not provide native async support
    - Implement observation-to-step mapping (Requirements 2.2): `llm` → `llm_response`; `tool` → `tool_call` + `tool_result`; `event` with `role == "user"` → `user_message`; other event roles → silently skip; `error` field non-null → `error` step; unrecognized types → skip + warning
    - Sort steps by ascending timestamp (default); configurable behavior via `TRAJECTORY_STEP_ORDER` env var (`reorder` | `reject`). When reordering, re-assign their zero-based `index` fields sequentially (from 0 to N-1) to ensure the index matches their final position in the ordered list.
    - Populate missing required fields with typed nulls; append `WarningEntry` for each; append `WarningEntry` for data quality issues
    - Catch `AuthenticationError`, `NotFoundError`, `TimeoutError` and return `LoadResult` with typed `LoadErrorCode`
    - Implement `async def load_file(self, content: str, file_name: str) -> LoadResult`: validate content byte length ≤ 50 MB (raise/return error if exceeded); delegate to `TrajectoryParserRegistry.parse(content, file_name)`; wrap I/O errors per Requirements 11.4–11.7; return same `LoadResult` shape as `load()`
    - _Requirements: 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 3.2 Write unit tests for `TrajectoryLoader`
    - Mock Langfuse SDK; test each observation-type mapping, warning generation, and each error-code path
    - Test `load_file` with content > 50 MB → returns appropriate error
    - Test `load_file` delegation to registry (mock registry; verify `parse()` called with correct args)
    - _Requirements: 2.2, 2.3, 2.4, 2.5_

- [ ] 15. Parser infrastructure — `TrajectoryParserRegistry` and built-in parsers
  - [ ] 15.1 Implement `TrajectoryParser` protocol and `TrajectoryParserRegistry`
    - Create `trajectory_eval/loader/parsers/` sub-package with `__init__.py`
    - Create `trajectory_eval/loader/parsers/base.py` defining the `TrajectoryParser` protocol: `format_name: str`, `can_parse(raw_data: str) -> bool`, `parse(raw_data: str, file_name: str) -> LoadResult`
    - Create `trajectory_eval/loader/parser_registry.py` implementing `TrajectoryParserRegistry`:
      - `__init__`: initialize empty ordered list of parsers; auto-register all built-in parsers (import and register `OpenAIMessagesParser`)
      - `register(parser)`: append new parser; if `format_name` already exists, replace in-place preserving order
      - `parse(raw_data, file_name)`: iterate parsers in order; call `can_parse()` catching all exceptions (treat as False); call `parse()` on first match; return `LoadResult(success=False, error_message="Unrecognized trajectory format.")` if no match
    - Auto-registration happens at module import time (not FastAPI startup) so registry works in tests without starting the full application
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ] 15.2 Implement `OpenAIMessagesParser`
    - Create `trajectory_eval/loader/parsers/openai_messages.py`
    - Implement `can_parse(raw_data)`: return True iff raw_data is a valid JSON array where every element has a `role` field of type string; return True for an empty array; return False (not raise) for any malformed input
    - Implement `parse(raw_data, file_name)` applying the full role→Step mapping:
      - `"system"` → silently skipped
      - `"user"` → `user_message` Step; `content` → `prompt` (null if absent/null)
      - `"assistant"` → If `tool_calls` is present and non-empty: if `content` is present and non-null, maps to an `llm_response` (`content` → `response`). Then, maps each item in `tool_calls` to a consecutive `tool_call` Step (`function.name` → `tool_name`, `function.arguments` parsed as JSON -> `tool_input`). Otherwise (no `tool_calls`), maps to a single `llm_response` (`content` → `response`, null if absent).
      - `"tool"` → `tool_result` Step; `content` → `tool_output` (null if absent/null)
      - any other role → silently skipped, append `WarningEntry` with message `"Skipped element at index <i>: unrecognized role '<role>'"`
    - Assign synthetic timestamps: Unix epoch (1970-01-01T00:00:00Z) + `step_index` seconds; `latency_ms = 0`, `token_count = 0`, `cost_usd = 0.0`
    - Set `Trajectory.start_time` = epoch + 0 s; `end_time` = epoch + (N−1) s; both = epoch if Steps list is empty
    - Derive `Trajectory.id` from `file_name` by stripping the last extension only (e.g. `"run.v2.json"` → `"run.v2"`); set `source_platform = "openai_messages"`; `agent_name = None`; `total_latency_ms = 0`; `total_token_count = 0`; `total_cost_usd = 0.0`
    - If an element is missing `role` or `role` is not a string, return `LoadResult(success=False, error_message="Parse error (openai_messages): element at index <i> is missing a string 'role' field")`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [ ]* 15.3 Write unit tests for `TrajectoryParserRegistry` and `OpenAIMessagesParser`
    - `TrajectoryParserRegistry` tests: registration order preserved; duplicate `format_name` replaces in-place; `can_parse()` exception swallowed and next parser tried; no-match returns "Unrecognized trajectory format."
    - `OpenAIMessagesParser.can_parse()` tests: valid array → True; empty array → True; non-array → False; array with missing role → False; exception input (non-JSON) → False
    - `OpenAIMessagesParser.parse()` tests: each role mapping (`user`, `assistant`, `tool`, `system` skip, unknown skip+warning); null `content` → null field; synthetic timestamp formula (step 0 = epoch, step 1 = epoch+1s, etc.); trajectory `id` derivation from file stem; empty array → empty Steps, start_time = end_time = epoch
    - _Requirements: 12.2, 12.3, 12.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [ ]* 15.4 Write property tests for parser registry and OpenAI parser (P11, P12)
    - Create `tests/test_parser_registry.py`
    - **Property 11: Parser registry first-match dispatch** — any raw data; parsers A then B both return True from `can_parse()`; registry calls `parse()` on A not B. If A's `can_parse()` throws, registry calls B's `parse()`.
    - Create `tests/test_parsers.py`
    - **Property 12: OpenAI messages round-trip step count** — any valid messages array with K elements where `role ∈ {user, assistant, tool}` → parser produces exactly K Steps
    - `settings(max_examples=100)` on each test
    - **Validates: Requirements 12.2, 13.2**

- [ ] 4. Rule generator — node-level strategies
  - [ ] 4.1 Implement abstract `NodeRuleGeneratorStrategy` and `RuleGenerator` orchestrator
    - Create `trajectory_eval/generator/base.py` with abstract `NodeRuleGeneratorStrategy.generate(step: Step, seq_start: int) -> list[Rule]`
    - Create `trajectory_eval/llm/base.py` with `LLMClient` protocol: `async def complete(self, prompt: str, timeout: float) -> str`
    - Create `trajectory_eval/llm/openai_client.py` with `OpenAILLMClient` as the default implementation
    - Create `trajectory_eval/generator/rule_generator.py` with `async def generate(trajectory: Trajectory) -> RuleSet`; accept `llm_client: LLMClient | None = None` in `__init__`
    - Implement ID counter logic: `<step_type>_<step_index>_<seq>`; global rules use `global_<seq>`
    - _Requirements: 3.7, 3.8, 3.9, 4.3_

  - [ ] 4.2 Implement `ToolCallRuleGenerator` strategy
    - Construct `EqualityCheck` for tool-name equality
    - Construct `KeyPresenceCheck` for each key in `tool_input`
    - Construct `EqualityCheck` for each string/numeric-valued key in `tool_input`
    - Set `Rule.pseudocode` by calling `expression_to_pseudocode(expression)` on each
    - Set `Rule.confidence = RuleConfidence.high` for all generated rules
    - _Requirements: 3.2, 3.9_

  - [ ] 4.3 Implement `LLMResponseRuleGenerator` strategy
    - Extend the LLM call to use a structured JSON response schema: `{ "soft_rule_description": str, "anchor_facts": [{"value": str, "justification": str}] }` (0–3 anchor facts, each value ≤200 chars)
    - For each returned anchor fact: construct `ContainsCheck(container=f"step[{i}].response", value=anchor_fact.value)`; set `Rule.pseudocode` from IR; set `Rule.justification = anchor_fact.justification`
    - Assign `confidence = high` if `anchor_fact.value` is a case-sensitive substring of `tool_input` or `tool_output` of any step within `RULE_ANCHOR_WINDOW` steps (default 2, read from env); otherwise `confidence = medium`
    - On LLM failure or timeout (30 s): produce zero anchor Hard_Rules, append `WarningEntry`, fall back to templated Soft_Rule description
    - Soft rule: `expression = None`; `pseudocode` = "The response at step [i] is relevant to and consistent with the prompt at the preceding step." Ensure a safety check that `step_index > 0` before attempting to reference a preceding step, handling index 0 gracefully.
    - _Requirements: 3.3, 3.9, 3.10, 14.2_

  - [ ] 4.4 Implement `ToolResultRuleGenerator` strategy
    - Construct `KeyPresenceCheck` for each JSON key in parsed tool output
    - Construct `TypeCheck` for each key's observed type
    - Set `Rule.pseudocode` by calling `expression_to_pseudocode(expression)` on each
    - Set `Rule.confidence = RuleConfidence.high` for Hard_Rules; `RuleConfidence.medium` for Soft_Rules
    - Soft rule: `expression = None`; `pseudocode` = "The tool result at step [i] is a plausible response to the tool input provided at the preceding tool_call step." (async LLM with fallback). Ensure a safety check that the preceding step exists and is of type `tool_call` before referencing it.
    - _Requirements: 3.4, 3.9, 3.10_

  - [ ] 4.5 Implement `UserMessageRuleGenerator` and `ErrorStepRuleGenerator` strategies
    - `user_message`: construct `LenGtZeroCheck(target="step[i].prompt")`; set `pseudocode` from IR
    - `error`: construct `LenGtZeroCheck(target="step[i].error_message")` and `EqualityCheck(left="step[i].index", right=<observed_index>)`; set `pseudocode` from IR
    - Set `Rule.confidence = RuleConfidence.low` for all generated rules
    - _Requirements: 3.5, 3.6_

  - [ ]* 4.6 Write property tests for node-level rule generation (P3, P4, P5)
    - Create `tests/test_rule_generator.py`
    - **Property 3: Every step gets at least one rule** — any valid Trajectory → RuleSet has a rule for each step index
    - **Property 4: Tool-call hard rules are complete** — any `tool_call` step with non-empty tool name and non-empty `tool_input` → rules include an `EqualityCheck` for the tool name, a `KeyPresenceCheck` per key, and an `EqualityCheck` per string/numeric-valued key; all `expression` fields are non-`None`
    - **Property 5: Rule IDs are unique within a RuleSet** — any valid Trajectory → all `Rule.id` values in the RuleSet are distinct
    - **Property 13: Anchor Hard-Rule confidence assignment** — for any `llm_response` step where the LLM returns K anchor facts, each anchor Hard_Rule has confidence `high` if its value is a case-sensitive substring of a nearby tool step's input/output within the window, and `medium` otherwise; no anchor Hard_Rule has confidence `low`
    - `settings(max_examples=100)` on each test
    - **Validates: Requirements 3.1, 3.2, 3.7, 3.3, 14.2**

- [ ] 5. Rule generator — global rules and tolerance bounds
  - [ ] 5.1 Implement `GlobalRuleGenerator`
    - Create `trajectory_eval/generator/global_rule_generator.py`
    - Generate step-count tolerance bounds using `RULE_TOLERANCE_MARGIN` (default `0.2`): construct two `BoundsCheck` expressions with `lower` and `upper` computed at generation time from the observed count and the margin
    - Generate `StepTypePresenceCheck` for each distinct `StepType` observed
    - Generate `BoundsCheck` expressions for cost and latency bounds, hardcoding the observed values at generation time
    - Set `Rule.pseudocode` from `expression_to_pseudocode(expression)` for all hard rules
    - Set `Rule.confidence = RuleConfidence.medium` for Hard_Rules; `RuleConfidence.low` for Soft_Rules
    - Generate two global Soft_Rules with `expression = None` (Requirements 4.2)
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 5.2 Write property test for global tolerance bounds (P8)
    - **Property 8: Global tolerance-bounds rules are within margin** — any Trajectory with count C and margin T → lower bound is `C * (1 − T)`, upper bound is `C * (1 + T)`; same for cost and latency
    - `settings(max_examples=100)`
    - **Validates: Requirements 4.1**

- [ ] 6. Checkpoint — core backend logic
  - Ensure all tests pass for models, loader, and rule generator. Ask the user if questions arise.

- [ ] 7. Rule persistence — `RuleStore`
  - [ ] 7.1 Implement abstract `RuleStore`, `RuleStoreFactory`, and `SQLiteRuleStore`
    - Create `trajectory_eval/store/base.py` with `RuleStore` ABC: `@abstractmethod async def save`, `@abstractmethod async def load`, `@abstractmethod async def list_all`
    - Create `trajectory_eval/store/factory.py` with `RuleStoreFactory.create() -> RuleStore` reading `RULE_STORE_BACKEND` env var and instantiating the correct backend
    - Register the store instance in FastAPI's lifespan context so it is injected via `Depends()` — no global singletons
    - Create `trajectory_eval/store/sqlite_store.py` using `aiosqlite` with fully `async def` implementations
    - Initialize the database connection with WAL mode enabled (`PRAGMA journal_mode=WAL;`) and a busy timeout (`PRAGMA busy_timeout=5000;`) to prevent database locked errors under concurrent API access
    - Apply SQLite schema from design (`rule_sets` table + index); use `RULE_STORE_SQLITE_PATH` env var
    - Implement rollback on disk/permission failure; surface error message per Requirements 6.6
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ] 7.2 Implement `JSONRuleStore`
    - Create `trajectory_eval/store/json_store.py`; use `RULE_STORE_JSON_PATH` env var; implement all methods as `async def`
    - Use `aiofiles` for non-blocking file I/O
    - Implement atomic write (write to temp file, then `os.replace`) to prevent corruption on concurrent writes
    - _Requirements: 6.1, 6.2, 6.3, 6.6_

  - [ ]* 7.3 Write unit tests for `RuleStore` backends
    - SQLite: save → load round-trip with in-memory DB; list returns correct summaries
    - JSON: save → load round-trip with temp file; list returns correct summaries
    - Test "not found" path for both backends
    - _Requirements: 6.3, 6.4, 6.5_

- [ ] 8. Rule exporter
  - [ ] 8.1 Implement `PseudocodeTranslator`
    - Create `trajectory_eval/exporter/pseudocode_translator.py`
    - Implement `translate(rule: Rule) -> str` using a `match rule.expression` statement with one branch per `PseudocodeExpression` variant (see design for the full `match` skeleton)
    - When `rule.expression is None` (soft rule or user-edited hard rule): return `# TODO: manual implementation required — {rule.description}` and flag a warning in `ExportResult`
    - No string parsing of `rule.pseudocode` — translation always operates on the typed IR
    - Write unit tests directly in this task: one test per expression variant to assert the exact `assert` string produced; one test for the `None` → `# TODO` path
    - _Requirements: 7.4, 7.6_

  - [ ] 8.2 Implement `RuleExporter` — pytest output
    - Create `trajectory_eval/exporter/rule_exporter.py`
    - Resolve `output_dir` as `Path(EXPORT_OUTPUT_DIR) / rule_set.trajectory_id`; create directory (including parents) if absent. When exporting, overwrite any existing files of the same name inside the export directory, preserving unrelated files.
    - Generate `test_hardcoded_rules.py`: one test function per approved `Hard_Rule`, named `test_step_{index}_{rule_id}` or `test_global_{rule_id}`, with docstring from plain-English description and translated `assert` statement
    - For step-scoped test functions, ensure the first line of the function body defines the local variable `step = trajectory.steps` so that expressions like `step[i]` execute correctly without causing a `NameError`
    - Generate `conftest.py` with `--trajectory-path` fixture as specified in design
    - Populate `ExportResult.output_dir` with the resolved absolute path string
    - Skip generation when no approved hard rules; return appropriate message. Generate a `README.md` file in the export directory with instructions on how to install dependencies and run the generated tests.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [ ] 8.3 Implement `RuleExporter` — DeepEval YAML output
    - Generate `soft_rule_evals.yaml` with `step_evaluations` and `global_evaluations` keys
    - Set `name`, `criteria`, `input`, `actual_output` per Requirements 8.2; use `""` for null prompt/response
    - Emit pseudocode as YAML line comment above each entry's `name` field. Because standard `PyYAML` does not support comments, write this output using a custom formatter or string manipulation to insert comments correctly.
    - Skip generation when no approved soft rules; surface appropriate messages on error. Overwrite existing files of the same name on export.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 8.4 Write property tests for exporter (P7, P9)
    - Create `tests/test_export.py`
    - **Property 7: Export passes only approved rules** — any RuleSet with mixed statuses → exporter output contains only `approved` rules; no `pending` or `rejected` rules appear
    - **Property 9: Soft-rule YAML fields are well-formed** — any approved Soft_Rule with non-null prompt and response → YAML entry has non-empty `name`, `criteria`, `input` = step prompt, `actual_output` = step response
    - `settings(max_examples=100)`
    - **Validates: Requirements 5.7, 8.1, 8.2**

  - [ ]* 8.5 Write unit tests for `RuleExporter` and `expression_to_pseudocode`
    - Test each `PseudocodeExpression` variant via `expression_to_pseudocode()` — assert the expected display string
    - Test `RuleExporter` happy path: pytest file structure, function naming, docstring placement, correct `assert` strings
    - Test `expression = None` path: `# TODO` placeholder emitted, warning added to `ExportResult`
    - Test YAML structure: keys present, null fields become `""`
    - _Requirements: 7.2, 7.3, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4_

- [ ] 9. FastAPI REST API layer
  - [ ] 9.1 Implement `POST /api/v1/trajectories/load` endpoint
    - Wire `TrajectoryLoader.load()` → `RuleGenerator.generate()` → return `{trajectory, rule_set, warnings}`
    - Map `LoadResult` errors to HTTP 401 (auth failure), HTTP 404 (trace not found), HTTP 422 (input validation), HTTP 504 (timeout), or 500 (unexpected)
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 10.2, 10.3, 10.4, 10.5_

  - [ ] 9.4 Implement `POST /api/v1/trajectories/load-file` endpoint
    - Accept request body `{ "file_content": str, "file_name": str }`
    - Wire `TrajectoryLoader.load_file(content, file_name)` → `RuleGenerator.generate(trajectory)` → return `{trajectory, rule_set, warnings}`
    - Map `LoadResult` errors: file not found → HTTP 404; file unreadable → HTTP 422; unrecognized format → HTTP 422; malformed content → HTTP 422; file too large → HTTP 413
    - Response shape identical to `POST /trajectories/load`
    - _Requirements: 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [ ] 9.2 Implement rule-set CRUD and export endpoints
    - `GET /api/v1/rule-sets` → `RuleStore.list_all()`
    - `GET /api/v1/rule-sets/{trajectory_id}` → `RuleStore.load()`; 404 if not found
    - `POST /api/v1/rule-sets` → `RuleStore.save()`; surface save errors
    - `POST /api/v1/rule-sets/{trajectory_id}/export` → `RuleExporter.export(rule_set, output_dir)`; return `ExportResult` (including `output_dir`) so the UI can display where files were written
    - Inject `RuleStore` via `Depends(get_rule_store)` where `get_rule_store` yields the instance created by `RuleStoreFactory` at startup
    - _Requirements: 5.7, 6.1, 6.3, 6.4, 6.5, 6.6, 7.1, 7.8, 8.5_

  - [ ]* 9.3 Write integration tests for API endpoints
    - `POST /api/v1/trajectories/load`: mock Langfuse SDK; verify response shape and rule counts
    - `POST /api/v1/rule-sets/{trajectory_id}/export`: mock approved rule set; verify `ExportResult` fields
    - `POST /api/v1/trajectories/load-file` with a valid OpenAI messages JSON payload; verify `trajectory.source_platform == "openai_messages"` and rule_set shape
    - Use `httpx.AsyncClient` with FastAPI `app` as ASGI transport
    - _Requirements: 2.1, 6.1, 7.1_

- [ ] 10. Checkpoint — full backend
  - Ensure all backend tests pass, including integration tests. Ask the user if questions arise.

- [ ] 11. Frontend — TypeScript types and API client
  - [ ] 11.1 Generate or author TypeScript types from the OpenAPI schema
    - Run `openapi-typescript` against `http://localhost:8000/openapi.json` (or copy schema) to generate `frontend/src/api/types.ts`
    - Create `frontend/src/api/client.ts` with typed wrappers for all five API endpoints
    - Add typed wrapper for `POST /api/v1/trajectories/load-file` to `frontend/src/api/client.ts`
    - _Requirements: 5.1, 5.2_

- [ ] 12. Frontend — HomeScreen
  - [ ] 12.1 Implement `HomeScreen` component
    - Create `frontend/src/screens/HomeScreen.tsx`
    - Render two tabs on the home screen: "Trace ID" tab (existing Langfuse form) and "Local File" tab (new)
    - "Local File" tab: file picker input (accept `.json`) with 50 MB client-side size guard; optional "Agent Name" text input
    - On file submit: validate non-empty selection; if file > 50 MB show inline validation error without API call; otherwise call `POST /api/v1/trajectories/load-file` via React Query mutation; show loading spinner; disable submit while loading
    - On success: navigate to `ReviewScreen` (identical to Langfuse success path)
    - On error: show `LoadResult.error_message` in visible error area; re-enable submit
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.2, 11.9, 11.10_

  - [ ]* 12.2 Write component tests for `HomeScreen`
    - Verify form validation (empty Trace ID blocked, length > 200 blocked)
    - Verify loading state disables submit button
    - Verify error message renders on API error
    - "Local File" tab: no file selected → submit blocked with validation message
    - "Local File" tab: file > 50 MB → client-side error, no API call
    - "Local File" tab: API success → navigates to ReviewScreen
    - "Local File" tab: API error → error message displayed, submit re-enabled
    - _Requirements: 10.1, 10.2, 10.5_

- [ ] 13. Frontend — ReviewScreen and rule interactions
  - [ ] 13.1 Implement `ReviewScreen` layout and `SummaryBar`
    - Create `frontend/src/screens/ReviewScreen.tsx`
    - Two-panel layout: left panel = `TrajectoryPanel` (step list); right panel = `RuleReviewPanel`
    - `SummaryBar` shows: step count, token count, cost (6 decimal places), latency ms
    - _Requirements: 5.1, 10.6_

  - [ ] 13.2 Implement `RuleCard` component
    - Display: description, pseudocode, type badge (Hard/Soft), scope badge (global / step N), status badge (pending/approved/rejected)
    - Display confidence badge (`High` / `Medium` / `Low`) on each Rule card alongside the existing type, scope, and status badges
    - For LLM-curated anchor Hard_Rules (where `Rule.justification` is non-null): display justification as a tooltip or sub-label below the description; for all other rules, omit the justification display area entirely
    - "Approve" / "Reject" / "Edit" buttons wired to local state handlers
    - Edit mode: editable description and pseudocode fields with "Save" and "Cancel" buttons; Save sets status to `pending`; Cancel restores original values
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 14.3, 14.5_

  - [ ] 13.3 Implement live rule counts, "Approve All", and "Export" button
    - Live counts (approved / rejected / pending) update immediately on every status change
    - Add a confidence filter control above the rule list: three independent toggles "High", "Medium", "Low", all enabled by default; toggling off hides matching rules without changing their status; filter state is in-memory and resets on page reload
    - "Approve All": applies only to currently visible (non-confidence-filtered) pending rules; hidden rules are unaffected; leave `rejected` unchanged
    - "Export": disabled when zero approved rules; shows "No approved rules to export." message; otherwise calls `POST /api/v1/rule-sets/{trajectory_id}/export` and displays `ExportResultBanner`
    - `ExportResultBanner` shows the resolved `output_dir` path, the list of generated file names, and any warnings — so the user always knows where the files landed
    - _Requirements: 5.6, 5.7, 5.8, 5.9, 14.4, 14.6_

  - [ ]* 13.4 Write component tests for `RuleCard` and `ReviewScreen` rule interactions
    - Approve, Reject: status badge updates immediately
    - Edit + Save: description/pseudocode updated, status → `pending`
    - Edit + Cancel: original values restored, status unchanged
    - Approve All: pending count → 0, rejected count unchanged
    - Export button disabled when 0 approved; shows message
    - Confidence filter: toggling off "Low" hides low-confidence rules; toggling back on restores them; rule statuses are unchanged
    - Approve All with filter: only visible pending rules are approved; hidden rules retain original status
    - Justification tooltip: present for anchor Hard_Rules with non-null justification; absent for other rules
    - Create `tests/test_rule_review.py` for **Property 6: Approve-All does not affect rejected rules** and **Property 14: Confidence filter does not mutate rule status**
      - **Property 6: Approve-All does not affect rejected rules** — any RuleSet with some rejected rules → after Approve-All, all rejected rules remain rejected, all pending → approved
      - **Property 14: Confidence filter does not mutate rule status** — any RuleSet + any combination of confidence filter toggles → after toggling all back on, every rule's status/description/pseudocode/confidence is identical to the pre-filter state
      - `settings(max_examples=100)` on the Hypothesis test
      - **Validates: Requirements 5.6, 14.4, 14.6**
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 5.8, 5.9_

- [ ] 14. Final checkpoint — full stack
  - Ensure all backend and frontend tests pass. Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- The design document contains the full Pydantic v2 model schemas and SQLite DDL — use them verbatim.
- Property tests use **Hypothesis** with `settings(max_examples=100)`; each test carries a comment `# Feature: trajectory-eval-system, Property <N>: <text>`.
- All correctness properties (P1–P10) are tracked in `tests/test_serialization.py`, `tests/test_rule_generator.py`, `tests/test_rule_review.py`, and `tests/test_export.py` as specified in the design's Testing Strategy section.
- P11 (Parser registry first-match dispatch) is tracked in `tests/test_parser_registry.py`.
- P12 (OpenAI messages round-trip step count) is tracked in `tests/test_parsers.py`.
- P13 (Anchor Hard-Rule confidence assignment) is tracked in `tests/test_rule_generator.py`.
- P14 (Confidence filter does not mutate rule status) is tracked in `tests/test_rule_review.py`.
- Checkpoints at tasks 6, 10, and 14 ensure incremental validation before moving to the next layer.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.3"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "4.1"] },
    { "id": 4, "tasks": ["15.1"] },
    { "id": 5, "tasks": ["15.2"] },
    { "id": 6, "tasks": ["15.3", "15.4"] },
    { "id": 7, "tasks": ["4.2", "4.3", "4.4", "4.5"] },
    { "id": 8, "tasks": ["4.6", "5.1"] },
    { "id": 9, "tasks": ["5.2", "7.1"] },
    { "id": 10, "tasks": ["7.2", "8.1"] },
    { "id": 11, "tasks": ["7.3", "8.2", "8.3"] },
    { "id": 12, "tasks": ["8.4", "8.5", "9.1"] },
    { "id": 13, "tasks": ["9.4", "9.2"] },
    { "id": 14, "tasks": ["9.3", "11.1"] },
    { "id": 15, "tasks": ["12.1"] },
    { "id": 16, "tasks": ["12.2", "13.1"] },
    { "id": 17, "tasks": ["13.2"] },
    { "id": 18, "tasks": ["13.3"] },
    { "id": 19, "tasks": ["13.4"] }
  ]
}
```
