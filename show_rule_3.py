"""Examine the data_dep_3_command rule in detail."""

import json
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "eval_traj.py", "./example_traj.json"],
    capture_output=True,
    text=True,
    timeout=60,
)

rules = json.loads(result.stdout)

# Find data_dep_3_command
target = [r for r in rules if r["id"] == "data_dep_3_command"]

if target:
    rule = target[0]
    print("=" * 80)
    print("FOUND: data_dep_3_command")
    print("=" * 80)
    print()
    print(f"ID:                  {rule['id']}")
    print(f"Step Index:          {rule['step_index']}")
    print(f"Rule Type:           {rule['rule_type']}")
    print(f"Scope:               {rule['scope']}")
    print(f"Step Type:           {rule['step_type']}")
    print(f"Confidence:          {rule['confidence']}")
    print()
    print(f"Description:")
    print(f"  {rule['rule_description']}")
    print()
    print(f"Pseudocode:")
    print(f"  {rule['pseudocode']}")
    print()

    # Show custom fields if any
    custom_fields = {
        k: v
        for k, v in rule.items()
        if k
        not in [
            "id",
            "step_index",
            "rule_type",
            "scope",
            "step_type",
            "confidence",
            "rule_description",
            "pseudocode",
            "polarity",
        ]
    }
    if custom_fields:
        print(f"Additional fields:")
        for k, v in custom_fields.items():
            print(f"  {k}: {v}")
else:
    print("✗ Rule not found!")
