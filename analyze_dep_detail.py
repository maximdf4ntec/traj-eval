"""Detailed analysis of why the data_dependency rule didn't catch the step 2-3 discrepancy."""

from trajectory_eval.parsers.swe_bench import parse_swe_bench
from trajectory_eval.models.trajectory import StepType

trajectory = parse_swe_bench("example_traj.json")

print("=" * 80)
print("DATA DEPENDENCY ANALYSIS")
print("=" * 80)
print()

# Look at steps 2 and 3
step2 = trajectory.steps[2]
step3 = trajectory.steps[3]

print(f"Step 2: {step2.step_type}")
print(f"  Output: {repr(step2.tool_output[:80])}")
print()

print(f"Step 3: {step3.step_type}")
print(f"  Tool: {step3.tool_name}")
print(f"  Input: {step3.tool_input}")
print()

# Check what substring from step3's input appears in step2's output
print("Checking for substring matches:")
print("-" * 80)

if step3.tool_input:
    for key, val in step3.tool_input.items():
        val_str = str(val)
        found = val_str in step2.tool_output if step2.tool_output else False

        # Extract just the path part for clarity
        if "boltons" in val_str:
            print(f"\nKey '{key}':")
            print(f"  Value in step3: {val_str}")
            print(f"  Value found in step2 output: {found}")

            # Show what's actually in step2
            print(f"  Step2 output contains: {repr(step2.tool_output)}")

            # Check if similar paths exist
            if "/testbed/boltons" in step2.tool_output:
                print(f"  ✓ '/testbed/boltons' found in step2 output")
            if "/testbed/boltons2" in step2.tool_output:
                print(f"  ✓ '/testbed/boltons2' found in step2 output (different!)")

print()
print("=" * 80)
print("CONCLUSION")
print("=" * 80)
print("""
The data_dependency rule uses EXACT STRING MATCHING (substring search):
  
  if val_str in prior_result.tool_output:
      # Create a rule

Step 2 OUTPUT: /testbed/boltons2/tableutils.py
Step 3 INPUT:  /testbed/boltons/tableutils.py  ← Different! (no "2")

These are TWO DIFFERENT PATHS, so no substring match occurs.

Therefore, the rule CORRECTLY does NOT generate a data dependency assertion,
because the string used in step 3 does NOT appear verbatim in step 2's output.

This suggests the agent either:
  1. Used a hardcoded path (not derived from step 2's output)
  2. Corrected/modified the path from step 2
  3. The file actually exists at both locations

This is a potential QUALITY ISSUE that the current data_dependency rule design
cannot detect, because it only tracks exact verbatim data flow.
""")
