# Fix duplicate test method
with open("tests/test_swe_bench_parser.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find and fix the duplicate method
output_lines = []
i = 0
found_first_bracket = False

while i < len(lines):
    line = lines[i]

    # Check if this is the first test_removes_bracket_observation_prefix
    if (
        "def test_removes_bracket_observation_prefix(self):" in line
        and not found_first_bracket
    ):
        found_first_bracket = True
        # Keep this one and the next 3 lines
        output_lines.append(line)  # def line
        i += 1
        output_lines.append(lines[i])  # msg = line
        i += 1
        output_lines.append(lines[i])  # assert line
        i += 1
    # Check if this is the second (bad) test_removes_bracket_observation_prefix
    elif (
        "def test_removes_bracket_observation_prefix(self):" in line
        and found_first_bracket
    ):
        # Skip until we find the next def
        while i < len(lines) and not (
            lines[i].strip().startswith("def test_") and i > 150
        ):
            i += 1
        continue
    else:
        output_lines.append(line)
        i += 1

# Write back
with open("tests/test_swe_bench_parser.py", "w", encoding="utf-8") as f:
    f.writelines(output_lines)

print("Fixed duplicate method")
