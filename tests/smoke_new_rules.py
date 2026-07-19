"""Smoke tests for the 4 new hard rule classes."""

from datetime import datetime, timezone

from trajectory_eval.models.trajectory import Step, StepType, Trajectory
from trajectory_eval.generator.rules.terminal_state import TerminalStateRule
from trajectory_eval.generator.rules.tool_result_type import ToolResultTypeRule
from trajectory_eval.generator.rules.llm_format import LlmResponseFormatRule
from trajectory_eval.generator.rules.llm_grounding import LlmGroundingRule

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _step(idx: int, stype: StepType, **kw) -> Step:
    return Step(index=idx, step_type=stype, timestamp=_EPOCH, **kw)


def _traj(*steps: Step) -> Trajectory:
    return Trajectory(id="test", start_time=_EPOCH, end_time=_EPOCH, steps=list(steps))


# ── Rule j: TerminalStateRule ─────────────────────────────────────────────

t_good = _traj(
    _step(0, StepType.user_message, prompt="fix the bug"),
    _step(1, StepType.llm_response, response="The fix is complete and all tests pass"),
)
rules = TerminalStateRule.from_trajectory(t_good)
assert len(rules) == 1 and rules[0].polarity.value == "positive", f"Got {rules}"

t_bad = _traj(_step(0, StepType.llm_response, response="Running tests..."))
rules2 = TerminalStateRule.from_trajectory(t_bad)
assert len(rules2) == 1 and rules2[0].polarity.value == "negative"
print("Rule j (terminal_state): PASS")

# ── Rule k: ToolResultTypeRule ────────────────────────────────────────────

json_output = '{"key": "value"}'
t_json = _traj(
    _step(0, StepType.tool_call, tool_name="get_data", tool_input={"q": "x"}),
    _step(1, StepType.tool_result, tool_output=json_output),
)
rules_k = ToolResultTypeRule.from_trajectory(t_json)
assert len(rules_k) == 1 and rules_k[0].detected_type.value == "json"
assert rules_k[0].is_valid is True
print("Rule k (json): PASS")

py_output = "def hello():\n    return 42"
t_py = _traj(
    _step(0, StepType.tool_call, tool_name="view_file", tool_input={"f": "a.py"}),
    _step(1, StepType.tool_result, tool_output=py_output),
)
rules_py = ToolResultTypeRule.from_trajectory(t_py)
assert len(rules_py) == 1 and rules_py[0].detected_type.value == "python"
print("Rule k (python): PASS")

# ── Rule l: LlmResponseFormatRule ─────────────────────────────────────────

t_fmt_ok = _traj(
    _step(0, StepType.user_message, prompt="Return the result as JSON"),
    _step(1, StepType.llm_response, response='{"result": 42}'),
)
rules_l = LlmResponseFormatRule.from_trajectory(t_fmt_ok)
assert len(rules_l) == 1 and rules_l[0].is_valid is True
assert rules_l[0].requested_format == "json"
print("Rule l (valid json): PASS")

t_fmt_bad = _traj(
    _step(0, StepType.user_message, prompt="Return the result as JSON"),
    _step(1, StepType.llm_response, response="Here is the result: 42"),
)
rules_l_bad = LlmResponseFormatRule.from_trajectory(t_fmt_bad)
assert len(rules_l_bad) == 1
assert rules_l_bad[0].is_valid is False
assert rules_l_bad[0].polarity.value == "negative"
print("Rule l (invalid json flagged): PASS")

# ── Rule m: LlmGroundingRule ──────────────────────────────────────────────

t_grounded = _traj(
    _step(0, StepType.tool_call, tool_name="find", tool_input={"q": "x"}),
    _step(1, StepType.tool_result, tool_output="Found: src/utils/helpers.py"),
    _step(2, StepType.llm_response, response="I will modify `src/utils/helpers.py`"),
)
rules_m = LlmGroundingRule.from_trajectory(t_grounded)
# helpers.py is in prior context — no grounding violation
violations = [r.entity_value for r in rules_m]
assert "src/utils/helpers.py" not in violations, f"False positive: {violations}"
print("Rule m (grounded ref, no violation): PASS")

t_ungrounded = _traj(
    _step(0, StepType.tool_result, tool_output="nothing useful here"),
    _step(1, StepType.llm_response, response="Check `src/foo/bar.py` for the bug"),
)
rules_ug = LlmGroundingRule.from_trajectory(t_ungrounded)
assert any(
    r.entity_value == "src/foo/bar.py" for r in rules_ug
), f"Expected violation, got {[r.entity_value for r in rules_ug]}"
print("Rule m (ungrounded ref flagged): PASS")

print("\nAll smoke tests PASSED.")
