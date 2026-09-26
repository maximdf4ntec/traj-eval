# Design Proposal: Introduce Behavior IR (Artifact Graph)

## Background

The original implementation generates a behavior contract directly from a trajectory by analyzing the sequence of tool invocations. While this approach successfully extracts many useful regression rules (data lineage, parameter contracts, terminal state, etc.), it has one major limitation:

> The generated contract still describes **how the reference trajectory was executed**, rather than **what behavior must be preserved**.

This distinction is critical for CI regression testing. Two correct agents may solve the same task using different execution strategies while preserving identical behavior. A behavior contract should accept both.

For example:

```
Agent A:
    find
      ↓
    view
      ↓
    edit
      ↓
    python

Agent B:
    grep
      ↓
    python
      ↓
    edit
      ↓
    python
```

Both trajectories may successfully modify the same source file and validate the fix. A contract based on tool ordering would incorrectly classify the second execution as a regression.

---

# Problem Statement

The current architecture operates directly on the trajectory:

```
Trajectory
      ↓
Rule Generator
      ↓
Behavior Contract
```

As a result:

* workflow rules are based on a single execution strategy
* rule generators duplicate trajectory parsing logic
* dependencies are inferred from tool ordering rather than actual artifact usage
* adding new rule generators requires understanding raw trajectories again

Most importantly, the generated contract is **tool-centric** instead of **behavior-centric**.

---

# Proposed Solution

Introduce an intermediate semantic representation (IR) called the **Artifact Graph**.

The new architecture becomes:

```
Trajectory
      │
      ▼
Trajectory Normalizer
      │
      ▼
Entity Extractor
      │
      ▼
Artifact Graph (Behavior IR)
      │
      ▼
Behavior Contract Generator
      │
      ├── Data Lineage
      ├── Artifact Dependencies
      ├── Interface Rules
      ├── Environment Adaptation
      ├── Terminal State
      └── Performance Report
```

Instead of reasoning about tool invocations, all generators operate on a shared semantic model describing artifacts and their lifecycle.

---

# Artifact Graph

The Artifact Graph represents observable entities discovered during execution.

Typical entities include:

* files
* directories
* IDs
* URLs
* search results
* database objects
* tickets
* any externally referenced artifact

Each artifact stores its lifecycle events.

Example:

```
tableutils.py

VIEW
 ↓
MODIFY

--------------------

reproduce_issue.py

CREATE
 ↓
EXECUTE

--------------------

edge_cases.py

CREATE
 ↓
EXECUTE
 ↓
REMOVE
```

Unlike the original trajectory, this representation captures **state transitions** rather than execution order.

---

# Behavior Contract Generation

Every rule generator consumes the Artifact Graph instead of the normalized trajectory.

Examples:

## Data Lineage

Instead of verifying:

```
python follows create
```

the generator verifies:

```
Artifact executed

↓

Artifact previously created
```

---

## Dependencies

Dependencies are expressed between artifacts rather than tools.

Example:

```
tableutils.py

↓

modified before

↓

detailed_test.py executed
```

This is significantly more stable than tool ordering.

---

## Workflow

The previous implementation attempted to infer a behavioral backbone from tool roles.

This component is replaced by **required artifact lifecycles**.

Example:

```json
{
  "required_artifacts": [
    {
      "entity": "tableutils.py",
      "required_lifecycle": [
        "view",
        "modify"
      ]
    },
    {
      "entity": "reproduce_issue.py",
      "required_lifecycle": [
        "create",
        "execute"
      ]
    }
  ]
}
```

The validator now checks that required state transitions occurred, regardless of how the agent achieved them.

---

# Benefits

## More Stable Regression Tests

The contract becomes independent of:

* exact tool selection
* execution order
* retries
* exploratory actions
* additional debugging steps

As long as the required behavioral invariants are preserved, the trajectory passes.

---

## Shared Semantic Model

All rule generators consume the same intermediate representation.

This eliminates duplicated trajectory parsing and makes new rule generators significantly easier to implement.

---

## Better Extensibility

Future generators can be implemented without understanding individual tools.

Examples include:

* behavior coverage
* artifact consistency
* cleanup validation
* unused artifact detection
* execution optimization
* PromptDNA metrics

All of these naturally operate on the Artifact Graph.

---

# Required Changes

The proposed refactoring consists of four major steps.

1. **Introduce `EntityExtractor`**

   * Extract artifacts from tool inputs, outputs, and user messages.

2. **Implement `ArtifactGraphBuilder`**

   * Construct the semantic graph describing artifact lifecycles and dependencies.

3. **Refactor rule generators**

   * Rewrite existing generators to consume the Artifact Graph instead of the raw trajectory.

4. **Replace Behavioral Backbone**

   * Remove the current sequence-based workflow extraction and replace it with artifact lifecycle validation.

---

# Expected Outcome

The Artifact Graph becomes the single semantic representation of execution.

```
Trajectory
      │
      ▼
Behavior IR (Artifact Graph)
      │
      ├── Behavior Contract
      ├── Python Regression Tests
      ├── OpenClaw Hooks
      ├── Hermes Hooks
      └── Performance Report
```

This architecture separates **trajectory parsing** from **behavior inference**, producing contracts that describe behavioral invariants rather than a particular execution strategy. As a result, generated regression tests become substantially more robust, reusable, and suitable for automated CI pipelines while remaining completely deterministic and independent of LLM-based reasoning.
