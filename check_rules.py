import json

with open("out_with_rules.json", encoding="utf-16") as f:
    rules = json.load(f)
print(f"Total rules generated: {len(rules)}")
print()
if rules:
    print("First 3 rules:")
    for r in rules[:3]:
        desc = r["rule_description"][:100]
        print(f"  [{r['id']}] {r['rule_type']}: {desc}")
    print()
    print("Sample rule structure (first 500 chars):")
    print(json.dumps(rules[0], indent=2)[:500])
