"""Check if data_dependency rules appear in the final JSON output."""

import json
import asyncio
from trajectory_eval.parsers.swe_bench import parse_swe_bench
from trajectory_eval.generator.hard_rules import generate_global_hard_rules
from trajectory_eval.generator.rules.data_dependency import DataDependencyRule


async def main():
    trajectory = parse_swe_bench("example_traj.json")

    # Generate directly
    direct_rules = DataDependencyRule.from_trajectory(trajectory)
    print(f"Direct generation: {len(direct_rules)} rules")
    if direct_rules:
        print(f"  First rule: {direct_rules[0].id}")

    # Generate via global hard rules
    global_rules = await generate_global_hard_rules(trajectory, embed_client=None)
    print(f"\nGlobal hard rules: {len(global_rules)} rules")

    # Count by type
    from collections import Counter

    rule_types = Counter(r.id.split("_")[0] for r in global_rules)
    print(f"Rule types: {dict(rule_types)}")

    # Check for data_dep rules
    data_dep_rules = [r for r in global_rules if r.id.startswith("data_dep")]
    print(f"\nData dependency rules in global output: {len(data_dep_rules)}")
    if data_dep_rules:
        for r in data_dep_rules[:3]:
            print(f"  - {r.id}: {r.rule_description[:80]}")
    else:
        print("  ✗ NO DATA_DEPENDENCY RULES IN GLOBAL OUTPUT")


asyncio.run(main())
