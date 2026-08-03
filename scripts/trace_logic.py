"""Detailed trace of data_dependency rule logic."""

from trajectory_eval.parsers.swe_bench import parse_swe_bench
from trajectory_eval.models.trajectory import StepType

trajectory = parse_swe_bench("example_traj.json")

print("=" * 80)
print("TRACING DATA_DEPENDENCY RULE LOGIC")
print("=" * 80)
print()

# Manually walk through the from_trajectory logic
steps = trajectory.steps
print(f"Total steps: {len(steps)}\n")

for step in steps:
    if step.step_type != StepType.tool_call or not step.tool_input:
        continue

    print(f"[Step {step.index}] TOOL_CALL: {step.tool_name}")
    print(f"  Input: {step.tool_input}")

    # Find prior tool_result
    prior_result = None
    for s in reversed(steps):
        if s.index < step.index and s.step_type == StepType.tool_result:
            prior_result = s
            break

    if prior_result is None:
        print(f"  → No prior tool_result found")
        print()
        continue

    if not prior_result.tool_output:
        print(f"  → Prior tool_result at step {prior_result.index} has empty output")
        print()
        continue

    print(
        f"  Prior tool_result at step {prior_result.index}: {repr(prior_result.tool_output[:80])}"
    )

    # Check each parameter
    found_any = False
    for key, val in step.tool_input.items():
        val_str = str(val)
        if len(val_str) < 4:
            print(f"    - '{key}': length < 4, skipped")
            continue

        # CURRENT LOGIC: "in"
        match_in = val_str in prior_result.tool_output
        # ALTERNATIVE LOGIC: "not in"
        match_not_in = val_str not in prior_result.tool_output

        if "boltons" in val_str or "tableutils" in val_str:
            print(f"    - '{key}': {repr(val_str[:60])}")
            print(f"      IN prior output:     {match_in}")
            print(f"      NOT IN prior output: {match_not_in}")
            found_any = True

    if not found_any and step.index in [3, 5]:
        print(f"    (checking other keys...)")
        for key, val in step.tool_input.items():
            val_str = str(val)
            match_in = val_str in prior_result.tool_output
            match_not_in = val_str not in prior_result.tool_output
            print(f"    - '{key}': IN={match_in}, NOT_IN={match_not_in}")

    print()

    if step.index > 10:
        break
