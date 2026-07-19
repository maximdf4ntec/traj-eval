"""Check the actual JSON output for data_dependency rules."""

import json

# Run eval and capture output
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "eval_traj.py", "./example_traj.json"],
    capture_output=True,
    text=True,
    timeout=60,
)

# Parse JSON output
try:
    rules = json.loads(result.stdout)
    print(f"Total rules in JSON output: {len(rules)}\n")

    # Look for data_dep rules
    data_dep_rules = [r for r in rules if r["id"].startswith("data_dep")]
    print(f"Data dependency rules: {len(data_dep_rules)}")

    if data_dep_rules:
        print("\nFirst 5 data_dep rules:")
        for r in data_dep_rules[:5]:
            print(f"  [{r['id']}] {r['rule_description'][:80]}")
    else:
        print("\n✗ NO DATA_DEP RULES IN JSON OUTPUT!")

    # List all rule types
    from collections import Counter

    rule_ids = [r["id"].split("_")[0] for r in rules]
    counts = Counter(rule_ids)
    print(f"\nRule type counts: {dict(sorted(counts.items()))}")

except json.JSONDecodeError as e:
    print(f"JSON decode error: {e}")
    print(f"Stdout length: {len(result.stdout)}")
    print(f"First 500 chars: {result.stdout[:500]}")
except Exception as e:
    print(f"Error: {e}")
    print(f"Stderr: {result.stderr[:500]}")
