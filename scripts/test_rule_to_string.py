"""Test the to_string() method on Rule instances."""

from trajectory_eval.models.rule import (
    HardRule,
    RulePolarity,
    RuleScope,
    ConfidenceLevel,
)
from trajectory_eval.models.trajectory import StepType

# Create a sample hard rule
rule = HardRule(
    id="test_rule_1",
    step_index=5,
    polarity=RulePolarity.positive,
    scope=RuleScope.step,
    step_type=StepType.tool_call,
    confidence=ConfidenceLevel.high,
    rule_description="This is a test rule for a tool call",
    pseudocode="step[5].tool_name == 'python'",
)

print("Testing to_string() method:")
print("=" * 80)
print(rule.to_string())
print("=" * 80)
