<!-- Based on/adapted from:
     https://github.com/github/awesome-copilot/blob/main/skills/agentic-eval/SKILL.md
     Unusually on-point here: trajectory-to-tests IS an eval-generation tool, so this skill applies
     to the library's own design (rule quality) as well as to Copilot's own output on this repo. -->
---
name: agentic-eval
description: Patterns for designing and validating rubric-based / LLM-as-judge evaluation logic. Activates when implementing or reviewing soft-rule (DeepEval) generation, designing a new rule type, or when a generated rule's quality is in question.
---

# Agentic Eval Skill

Since this library's core output *is* an evaluation artifact (hard rules + soft rules from a trajectory), the quality bar for the rules it generates matters as much as the quality bar for the code that generates them.

## Rubric design for soft rules
- A soft rule should state a single, judgeable criterion — "professional tone" is judgeable; "good response" is not (too many unstated dimensions bundled together).
- Prefer criteria an LLM-judge can answer with evidence pointing at specific trajectory spans, not just a vibe score. If the generated DeepEval YAML can't be traced back to *which part* of the trajectory justifies the score, the rule is under-specified.
- Distinguish rules that should be **binary judge output** (met/not met) from rules that need a **scaled metric** (0–1 relevance score) — don't default to one because it's easier to generate.

## Self-critique loop for rule generation
When generating rules from a trajectory (especially soft rules via an LLM call):
1. Generate candidate rule(s).
2. Run a second pass: "would this rule flag a trajectory that a human reviewer would actually consider correct?" (false-positive check) and "would it miss an obviously bad trajectory?" (false-negative check) — using held-out or synthetic edge-case trajectories, not the same one the rule was derived from.
3. Only emit rules that survive both checks, or flag low-confidence rules distinctly (e.g., a `confidence` field in the YAML) rather than presenting all generated rules as equally reliable.

## LLM-as-judge implementation notes
- Judge prompts belong in versioned template files, not inlined as f-strings scattered through the codebase — a prompt change should be a diffable, reviewable artifact, same as a code change.
- Any judge call in the pipeline gets logged (trajectory ID, prompt version, raw judge response) so a bad rule can be traced back to *why* the judge produced it — this is the auditability requirement from the code-reviewer skill, applied specifically to eval logic.
- Mock the judge LLM in unit tests (see `tdd/references/mocking.md`); use a small, explicitly-marked integration suite with real LLM calls to validate judge prompt changes before merging.

## Reviewing someone else's (or Copilot's) rule-generation code
Ask explicitly: "if I fed this the fixture trajectories in `tests/fixtures/`, would every generated rule be one a domain expert would sign off on without edits?" If the answer requires guessing, the generation logic needs more constraints or the fixture set needs more edge cases — don't ship on "looks plausible."
