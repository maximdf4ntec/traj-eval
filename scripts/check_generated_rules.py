"""Check what data_dependency rules are actually being generated."""

from trajectory_eval.generator.rules.data_dependency import DataDependencyRule
from trajectory_eval.parsers.swe_bench import parse_swe_bench

trajectory = parse_swe_bench("example_traj.json")

# Generate rules
rules = DataDependencyRule.from_trajectory(trajectory)

print(f"Generated {len(rules)} DataDependencyRule instances\n")

if rules:
    print("First 10 rules:")
    for i, rule in enumerate(rules[:10], 1):
        print(f"\n[{i}] {rule.id}")
        print(f"    Step {rule.step_index}: {rule.tool_name}")
        print(f"    Param: {rule.param_key}")
        print(f"    Value: {repr(rule.param_value[:60])}")
        print(f"    Source: Step {rule.source_step}")
else:
    print("NO RULES GENERATED")
    print("\nDebugging: Checking Step 3 manually...")

    step3 = trajectory.steps[3]
    step2 = trajectory.steps[2]

    print(f"\nStep 3: {step3.step_type}")
    print(f"  Input: {step3.tool_input}")
    print(f"\nStep 2: {step2.step_type}")
    print(f"  Output: {repr(step2.tool_output)}")

    # Check the logic
    for key, val in step3.tool_input.items():
        val_str = str(val)
        if len(val_str) < 4:
            print(f"  '{key}' skipped: length {len(val_str)} < 4")
            continue

        found = val_str in step2.tool_output
        not_found = val_str not in step2.tool_output

        print(f"  '{key}':")
        print(f"    Length: {len(val_str)}")
        print(f"    IN: {found}")
        print(f"    NOT IN: {not_found}")

        if not_found:
            print(f"    → Should create a rule! (val NOT in prior)")
