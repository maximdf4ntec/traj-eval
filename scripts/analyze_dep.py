"""Analyze the data dependency issue across steps."""

import json

with open("example_traj.json") as f:
    messages = json.load(f)

# Extract steps to understand the trajectory structure
print("Analyzing Step 2 (tool result) and Step 3 (tool call)...\n")

# In the trajectory parser, system messages are skipped, so we need to count
# Let's look at the raw messages and find what corresponds to steps 2-5

step_counter = 0
for i, msg in enumerate(messages):
    role = msg.get("role", "")

    if role == "system":
        continue

    content = msg.get("content", "")

    if step_counter == 2:
        print(f"=== Step 2 (msg[{i}]) - role: {role} ===")
        print(f"Content preview: {content[:200]}")
        print()

    elif step_counter == 3:
        print(f"=== Step 3 (msg[{i}]) - role: {role} ===")
        print(f"Content preview: {content[:200]}")
        if "boltons" in content.lower():
            # Extract the exact path mentioned
            import re

            paths = re.findall(r'/[^\s\'"]+tableutils\.py', content)
            if paths:
                print(f"Paths found: {paths}")
        print()

    elif step_counter == 5:
        print(f"=== Step 5 (msg[{i}]) - role: {role} ===")
        print(f"Content preview: {content[:200]}")
        if "boltons" in content.lower():
            import re

            paths = re.findall(r'/[^\s\'"]+tableutils\.py', content)
            if paths:
                print(f"Paths found: {paths}")
        print()

    if role != "system":
        step_counter += 1

    if step_counter >= 6:
        break
