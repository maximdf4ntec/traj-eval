# Requirements Document

## Introduction

This specification covers the redesign of the trajectory evaluation compiler output into two distinct artifacts: a **Behavior Contract** (deterministic, step-agnostic invariants for regression and runtime validation) and an **Execution Report** (behavioral observations and optimization metrics). The redesign eliminates step indices from the contract, introduces global rule deduplication, removes the ToolIndexRule entirely, and establishes a clear split between contract-eligible rules and metrics-only rules.

## Glossary

- **Contract_Compiler**: The pipeline component that transforms raw trajectory data into a Behavior Contract by running contract-eligible rules, deduplicating results, and emitting step-agnostic global invariants.
- **Behavior_Contract**: The primary output artifact containing deterministic, step-agnostic invariants suitable for regression testing and runtime validation.
- **Execution_Report**: The secondary output artifact containing behavioral observations, efficiency metrics, and unresolvable pattern flags.
- **Contract_Rule**: A rule implementation that produces deterministic invariants expressed in abstract terms (tool names, parameters, data flow) without positional step references.
- **Metrics_Rule**: A rule implementation that computes behavioral observations (rates, ratios, scores) for inclusion in the Execution Report only.
- **Global_Invariant**: A single constraint derived by merging all consistent occurrences of a pattern across the entire trajectory into one deduplicated rule.
- **Rule_Deduplicator**: The component that merges overlapping per-step observations from the same rule class into a single global constraint when the pattern is consistent.
- **Inconsistent_Pattern**: A pattern observed in a trajectory that contradicts itself across different occurrences and cannot be expressed as a single deterministic rule.
- **Rule_Target**: The abstract description of what a contract rule applies to, expressed via tool names, parameters, and data-flow relationships rather than step indices.
- **Compiled_Rule**: A single entry in the Behavior Contract's rules array, containing id, category, kind, target, constraint, and metadata fields.
- **Schema_Version**: The integer version identifier for the contract JSON schema, incremented on breaking changes.
- **Powerful_Couple**: A pair of tools that form a natural complement (start/stop, begin/commit, read/write, open/close, create/delete, lock/unlock) and are expected to appear in a fixed order.
- **Confidence_Threshold**: A configurable minimum observation count (default 3) above which a tool-ordering pattern is considered high-confidence without additional structural evidence.

## Requirements

### Requirement 1: Contract Schema Structure

**User Story:** As a downstream validator, I want the Behavior Contract to follow a well-defined JSON schema, so that I can parse and evaluate it programmatically.

#### Acceptance Criteria

1. THE Behavior_Contract SHALL contain a top-level `schema_version` field set to integer `2`.
2. THE Behavior_Contract SHALL contain a `generator` object with a `version` string field reflecting the trajectory_eval package version.
3. THE Behavior_Contract SHALL contain a `rules` array where each element is a Compiled_Rule.
4. WHEN a Compiled_Rule is emitted, THE Contract_Compiler SHALL include `id`, `category`, `kind`, `target`, `constraint`, `cardinality`, and `metadata` fields on the rule object.
5. THE Compiled_Rule `category` field SHALL be one of: `provenance`, `workflow`, `interface`, `adaptation`, `grounding`, `termination`.
6. THE Compiled_Rule `kind` field SHALL be an open string identifying the specific check type within its category.
7. THE Compiled_Rule `metadata` object SHALL contain `confidence` (one of `high`, `medium`, `low`) and `support` (positive integer) fields.
8. THE Compiled_Rule SHALL contain a `cardinality` field with one of the values: `all`, `any`, or `single`.
9. WHEN `cardinality` is `all`, THE rule SHALL apply to every instance of the target (e.g., every invocation of the specified tool must satisfy the constraint).
10. WHEN `cardinality` is `any`, THE rule SHALL apply to at least one instance of the target across the trajectory.
11. WHEN `cardinality` is `single`, THE rule SHALL apply to exactly one specific instance of the target (e.g., the first or last occurrence).

### Requirement 2: Step-Index Elimination from Contract

**User Story:** As a contract consumer, I want rules expressed in abstract terms so that contracts remain valid across trajectory variations that differ only in step ordering.

#### Acceptance Criteria

1. THE Behavior_Contract SHALL NOT contain any step index values, step numbers, or positional references within the `rules` array.
2. THE Rule_Target SHALL express constraints using tool names, parameter names, and data-flow relationships exclusively.
3. WHEN the Contract_Compiler encounters a data dependency, THE Contract_Compiler SHALL express the origin as a tool-name and output-field pair rather than a step index.
4. WHEN the Contract_Compiler encounters a tool ordering dependency, THE Contract_Compiler SHALL express the ordering as a tool-pair relationship (tool_a precedes tool_b) rather than step-index comparison.
5. THE Rule_Target `step_index` and `step_range` fields SHALL be removed from the contract schema.

### Requirement 3: Contract Rule Classification

**User Story:** As a system maintainer, I want a clear separation between rules that produce contract invariants and rules that produce metrics, so that each artifact contains only appropriate content.

#### Acceptance Criteria

1. THE Contract_Compiler SHALL classify DataDependencyRule as a Contract_Rule producing `provenance` category invariants.
2. THE Contract_Compiler SHALL classify ToolParamTypeRule as a Contract_Rule producing `interface` category invariants.
3. THE Contract_Compiler SHALL classify ToolParamCountRule as a Contract_Rule producing `interface` category invariants.
4. THE Contract_Compiler SHALL classify ToolSequenceRule as a Contract_Rule producing `workflow` category invariants.
5. THE Contract_Compiler SHALL classify ToolResultTypeRule as a Contract_Rule producing `interface` category invariants.
6. THE Contract_Compiler SHALL classify LlmResponseFormatRule as a Contract_Rule producing `interface` category invariants.
7. THE Contract_Compiler SHALL classify LlmGroundingRule as a Contract_Rule producing `grounding` category invariants.
8. THE Contract_Compiler SHALL classify TerminalStateRule as a Contract_Rule producing `termination` category invariants.
9. THE Contract_Compiler SHALL classify MutationMatcherRule as a Contract_Rule producing `adaptation` category invariants.

### Requirement 4: Metrics Rule Classification

**User Story:** As a system maintainer, I want metrics-only rules routed exclusively to the Execution Report so that the Behavior Contract contains only deterministic invariants.

#### Acceptance Criteria

1. THE Contract_Compiler SHALL classify RedundancyRateRule as a Metrics_Rule producing observations for the Execution_Report only.
2. THE Contract_Compiler SHALL classify TokenEfficiencyRule as a Metrics_Rule producing observations for the Execution_Report only.
3. THE Contract_Compiler SHALL classify MonotonicProgressRule as a Metrics_Rule producing observations for the Execution_Report only.
4. THE Contract_Compiler SHALL classify CycleBreakRule as a Metrics_Rule producing observations for the Execution_Report only.
5. THE Contract_Compiler SHALL NOT include Metrics_Rule outputs in the Behavior_Contract `rules` array.

### Requirement 5: ToolIndexRule Removal

**User Story:** As a system maintainer, I want the ToolIndexRule removed entirely because positional tool assertions are too trajectory-specific to serve as reusable invariants.

#### Acceptance Criteria

1. THE Contract_Compiler SHALL NOT include ToolIndexRule in the rule registry.
2. THE Contract_Compiler SHALL NOT emit any rule asserting that a specific tool must appear at a specific trajectory position.
3. WHEN the `tool_call_rules` facade function is invoked, THE Contract_Compiler SHALL exclude ToolIndexRule from its output.

### Requirement 6: Global Rule Deduplication

**User Story:** As a contract consumer, I want each invariant expressed exactly once regardless of how many times it was observed, so that the contract is concise and non-redundant.

#### Acceptance Criteria

1. WHEN multiple per-step observations from the same rule class describe the same constraint (identical tool, parameter, and constraint values), THE Rule_Deduplicator SHALL merge them into one Global_Invariant.
2. WHEN merging observations, THE Rule_Deduplicator SHALL set the `metadata.support` field to the count of merged observations.
3. WHEN merging observations, THE Rule_Deduplicator SHALL set the `metadata.confidence` field to the highest confidence level among the merged observations.
4. THE Rule_Deduplicator SHALL assign a unique `id` to each deduplicated Global_Invariant using the pattern `rule_{sequence_number:03d}`.
5. WHEN a ToolParamTypeRule observes the same tool and parameter with the same expected type across multiple steps, THE Rule_Deduplicator SHALL emit one Compiled_Rule with support equal to the observation count.
6. WHEN a DataDependencyRule observes the same tool-parameter originating from the same source tool and output field across multiple steps, THE Rule_Deduplicator SHALL emit one Compiled_Rule with support equal to the observation count.

### Requirement 7: Inconsistent Pattern Handling

**User Story:** As a contract consumer, I want contradictory patterns excluded from the contract and flagged separately, so that the contract contains only reliable invariants.

#### Acceptance Criteria

1. WHEN multiple observations from the same rule class produce contradictory constraints for the same target (e.g., same parameter traced to different origins), THE Rule_Deduplicator SHALL NOT emit a Compiled_Rule for that target.
2. WHEN an Inconsistent_Pattern is detected, THE Contract_Compiler SHALL record the conflicting observations in the Execution_Report as an unresolvable flag.
3. WHEN an Inconsistent_Pattern is detected, THE Contract_Compiler SHALL include the conflicting constraint values and observation count in the flag record.

### Requirement 8: Data Dependency Rule Redesign

**User Story:** As a contract consumer, I want data provenance rules that express origin relationships between tools rather than between step positions.

#### Acceptance Criteria

1. WHEN a tool parameter value originates from a prior tool output, THE DataDependencyRule SHALL express the constraint as `must_originate_from: {tool, output_field}` without referencing any step index.
2. THE DataDependencyRule Compiled_Rule target SHALL contain `tool` and `parameter` fields identifying the consuming tool and parameter.
3. THE DataDependencyRule Compiled_Rule constraint SHALL contain a `must_originate_from` object with `tool` (source tool name) and `output_field` (source output key) fields.
4. WHEN the same parameter of the same tool is observed originating from the same source tool and field across multiple occurrences, THE Rule_Deduplicator SHALL produce one Compiled_Rule with accumulated support.

### Requirement 9: Tool Sequence Rule Redesign

**User Story:** As a contract consumer, I want ordering rules that express which tool must precede which other tool, without step-index references and with confidence derived from structural evidence.

#### Acceptance Criteria

1. WHEN tool B consistently follows tool A (with A succeeding), THE ToolSequenceRule SHALL express the constraint as a `tool_pair` relationship: `{tool_a, tool_b, condition: "a_succeeds"}`.
2. THE ToolSequenceRule Compiled_Rule target SHALL contain a `tool_pair` field with the ordered tuple of tool names.
3. THE ToolSequenceRule Compiled_Rule constraint SHALL describe the ordering condition (`a_succeeds` or `a_fails`) and the expected behavior (`b_valid` or `b_blocked`).
4. WHEN the same tool-pair ordering is observed multiple times, THE Rule_Deduplicator SHALL emit one Compiled_Rule with support equal to the observation count.
5. WHEN tool B uses a parameter that originates from tool A's output (data-flow dependency), THE ToolSequenceRule SHALL assign `high` confidence to the ordering rule.
6. WHEN tool A and tool B form a complementary pair (start/stop, begin/commit, read/write, open/close, create/delete, lock/unlock), THE ToolSequenceRule SHALL assign `high` confidence to the ordering rule.
7. WHEN tool A precedes tool B three or more times (configurable threshold) without data-flow or complementary-pair evidence, THE ToolSequenceRule SHALL assign `high` confidence to the ordering rule.
8. WHEN tool A precedes tool B fewer than the configured threshold times and no data-flow or complementary-pair evidence exists, THE Contract_Compiler SHALL NOT emit a contract rule for that pair.
9. WHEN tool ordering is inconsistent (tool B is preceded by different tools in different occurrences with no resolvable pattern), THE Contract_Compiler SHALL NOT emit a contract rule and SHALL record the inconsistency in the Execution_Report flags.

### Requirement 10: Interface Rules Redesign (ParamType, ParamCount, ResultType, LlmFormat)

**User Story:** As a contract consumer, I want interface rules that describe tool parameter and output constraints in terms of tool identity rather than trajectory position.

#### Acceptance Criteria

1. THE ToolParamTypeRule Compiled_Rule target SHALL identify the tool by name and the parameter by key, without step indices.
2. THE ToolParamTypeRule Compiled_Rule constraint SHALL contain an `expected_type` field with the Python type name.
3. THE ToolParamCountRule Compiled_Rule target SHALL identify the tool by name, without step indices.
4. THE ToolParamCountRule Compiled_Rule constraint SHALL contain an `expected_count` field with the integer parameter count.
5. THE ToolResultTypeRule Compiled_Rule target SHALL identify the tool by name, without step indices.
6. THE ToolResultTypeRule Compiled_Rule constraint SHALL contain an `expected_format` field describing the output structure type.
7. THE LlmResponseFormatRule Compiled_Rule target SHALL use `response: "assistant"` to identify the LLM response, without step indices.
8. THE LlmResponseFormatRule Compiled_Rule constraint SHALL contain an `expected_format` field (e.g., `json`, `yaml`, `xml`).

### Requirement 11: Grounding and Termination Rules Redesign

**User Story:** As a contract consumer, I want grounding and termination rules expressed as trajectory-wide properties rather than step-anchored checks.

#### Acceptance Criteria

1. THE LlmGroundingRule Compiled_Rule target SHALL identify the entity being grounded and optionally the response context, without step indices.
2. THE LlmGroundingRule Compiled_Rule constraint SHALL describe the referential integrity requirement (entity must appear in prior tool outputs within context window).
3. THE TerminalStateRule Compiled_Rule target SHALL use `scope: "trajectory"` to indicate it applies to the trajectory as a whole.
4. THE TerminalStateRule Compiled_Rule constraint SHALL contain the `completion_keywords` list and the expected terminal condition.

### Requirement 12: Adaptation Rule Redesign (MutationMatcher)

**User Story:** As a contract consumer, I want adaptation rules that express failure-recovery behavior abstractly, so that I can verify agents adapt after tool failures regardless of trajectory position.

#### Acceptance Criteria

1. THE MutationMatcherRule Compiled_Rule target SHALL identify the tool whose failure triggers adaptation, without step indices.
2. THE MutationMatcherRule Compiled_Rule constraint SHALL describe the expected adaptation behavior (agent modifies approach after a tool call returns a failure keyword).
3. WHEN the same tool failure followed by adaptation is observed multiple times, THE Rule_Deduplicator SHALL emit one Compiled_Rule with support equal to the observation count.
4. THE MutationMatcherRule Compiled_Rule category SHALL be `adaptation` and kind SHALL be `failure_recovery`.

### Requirement 13: Execution Report Structure

**User Story:** As a system operator, I want metrics and behavioral observations collected in a separate Execution Report, so that I can review optimization opportunities without conflating them with regression invariants.

#### Acceptance Criteria

1. THE Contract_Compiler SHALL produce an Execution_Report as a separate output artifact from the Behavior_Contract.
2. THE Execution_Report SHALL contain a `metrics` section with observations from all Metrics_Rules (RedundancyRateRule, TokenEfficiencyRule, MonotonicProgressRule, CycleBreakRule).
3. THE Execution_Report SHALL contain a `flags` section listing all Inconsistent_Patterns that could not be resolved into contract rules.
4. THE Execution_Report SHALL contain a `schema_version` field and a `generator` object matching the Behavior_Contract structure.

### Requirement 14: Compiler Pipeline Changes

**User Story:** As a developer, I want the compiler pipeline restructured to produce both artifacts in a single pass, so that I can invoke one entry point and receive the contract and report together.

#### Acceptance Criteria

1. THE Contract_Compiler SHALL accept a Trajectory and produce both a Behavior_Contract and an Execution_Report from a single invocation.
2. WHEN the Contract_Compiler processes a trajectory, THE Contract_Compiler SHALL route each rule's output to the appropriate artifact based on its classification (Contract_Rule or Metrics_Rule).
3. THE Contract_Compiler SHALL apply the Rule_Deduplicator to all Contract_Rule outputs before emitting the final Behavior_Contract.
4. THE Contract_Compiler SHALL preserve the YAML-driven configuration for enabling, disabling, and parameterizing individual rules.
5. IF a Contract_Rule raises an exception during execution, THEN THE Contract_Compiler SHALL log the error and continue processing remaining rules without failing the entire compilation.

### Requirement 15: Migration of Per-Step Rules to Global Rules

**User Story:** As a developer, I want per-step rule factories (ToolParamTypeRule, ToolParamCountRule) converted to trajectory-level factories so that they naturally produce global invariants.

#### Acceptance Criteria

1. THE ToolParamTypeRule SHALL implement a `from_trajectory` classmethod that scans all tool_call steps and collects type observations per (tool_name, parameter_key) pair.
2. THE ToolParamCountRule SHALL implement a `from_trajectory` classmethod that scans all tool_call steps and collects parameter count observations per tool_name.
3. WHEN the `from_trajectory` factory collects observations, THE rule class SHALL group them by target identity (tool name and parameter key) to support deduplication.
4. THE `tool_call_rules` facade function SHALL be deprecated and replaced by trajectory-level invocation through the HardRuleRunner.

### Requirement 16: Contract Serialization and Parsing

**User Story:** As a downstream system, I want to serialize the Behavior Contract to JSON and parse it back losslessly, so that contracts can be stored, transmitted, and reconstructed.

#### Acceptance Criteria

1. THE Contract_Compiler SHALL serialize the Behavior_Contract to JSON using the schema defined in Requirement 1.
2. THE Contract_Compiler SHALL provide a parser that reconstructs a Behavior_Contract object from valid JSON.
3. FOR ALL valid Behavior_Contract objects, serializing to JSON then parsing back SHALL produce an equivalent object (round-trip property).
4. WHEN invalid JSON is provided to the parser, THE parser SHALL return a descriptive error identifying the schema violation.
