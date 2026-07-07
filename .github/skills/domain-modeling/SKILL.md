<!-- Based on/adapted from:
     https://github.com/mattpocock/skills/blob/main/skills/engineering/domain-modeling/SKILL.md -->
---
name: domain-modeling
description: Actively build and sharpen trajectory-to-tests' domain model — challenge terms against GLOSSARY.md, catch inconsistent vocabulary, and update the glossary inline when new concepts emerge. Activates during design discussions, naming decisions, or when the same concept gets described two different ways.
---

# Domain Modeling Skill

A shared, precise vocabulary makes the codebase navigable and cuts tokens spent re-explaining concepts every session. This skill's job: keep `GLOSSARY.md` current and challenge sloppy or duplicate terminology as it appears, not after it's spread through five modules.

## Maintain GLOSSARY.md
If it doesn't exist, create it at the repo root with entries like:

```markdown
## Trajectory
A recorded sequence of agent steps (LLM turns + tool calls + tool responses) for one task execution, in a specific source format (OpenAI Messages, Anthropic Messages, Langfuse trace, ...).

## Hard rule
An assertion compiled to a pytest `assert` — deterministic, binary pass/fail, checked at test-run time. Example: "the trajectory must call `search_flights` before `book_flight`."

## Soft rule
A criterion compiled to DeepEval YAML — evaluated by an LLM-as-judge or metric, not a deterministic assert. Example: "the final response tone should be professional."

## Tool-provenance anchoring
The mechanism for distinguishing text that originated from a tool's actual output vs. text the LLM generated *about* a tool call (LLM response noise) when both appear adjacent in a trajectory.

## tool_call appropriateness
Whether a given tool call was a reasonable action given the trajectory state at that point — distinct from whether the tool call *succeeded*.
```

## When to challenge a term
- Two different names describing the same concept in different files → flag it, propose one, update both call sites and the glossary in the same change.
- A name that requires the reader to already know the answer to understand the question (`process()`, `handle_data()`, `_buffer`) → push for a name that states the concept.
- A new concept introduced in a PR/discussion without a glossary entry → add the entry as part of that change, not as separate cleanup debt.

## Stress-test with edge cases
When defining or refining a term, run it against edge cases before locking it in:
- Does "hard rule" still make sense for a rule that's deterministic but expressed as a *range* rather than exact match (e.g., "latency under 2s")? If ambiguous, the glossary entry needs a boundary case documented, not just the common case.
- Does "trajectory" cover a partial/truncated trajectory (agent still running, log cut off mid-task)? Decide explicitly and note it.

## Output
Any session that introduces or resolves a naming ambiguity ends with a glossary diff — even a one-line addition — so the next session (human or agent) doesn't re-litigate it.
