"""Tests for parse_contract helper and ContractParseError."""

import pytest

from trajectory_eval.models import (
    BehaviorContract,
    CompiledRule,
    ContractParseError,
    Evidence,
    EvidenceSource,
    RuleCardinality,
    RuleCategory,
    RuleMetadata,
    RuleTarget,
    parse_contract,
)
from trajectory_eval.models.rule import ConfidenceLevel


def _make_contract() -> BehaviorContract:
    """Build a minimal valid BehaviorContract for testing."""
    return BehaviorContract(
        evidence=Evidence(generated_from=EvidenceSource(trajectory_count=1)),
        rules=[
            CompiledRule(
                id="rule_001",
                category=RuleCategory.interface,
                kind="param_type",
                target=RuleTarget(tool="str_replace", parameter="old_str"),
                constraint={"expected_type": "str"},
                cardinality=RuleCardinality.all,
                metadata=RuleMetadata(confidence=ConfidenceLevel.high, support=3),
            ),
        ],
    )


class TestParseContractRoundTrip:
    """Validates: Requirements 16.2, 16.3"""

    def test_round_trip_preserves_equality(self) -> None:
        """Serializing then parsing produces an equivalent object."""
        contract = _make_contract()
        json_str = contract.model_dump_json()
        restored = parse_contract(json_str)
        assert restored == contract

    def test_round_trip_empty_rules(self) -> None:
        """Round-trip works with an empty rules list."""
        contract = BehaviorContract(
            evidence=Evidence(generated_from=EvidenceSource(trajectory_count=1)),
            rules=[],
        )
        json_str = contract.model_dump_json()
        restored = parse_contract(json_str)
        assert restored == contract

    def test_round_trip_via_model_validate_json_directly(self) -> None:
        """model_validate_json round-trip matches parse_contract."""
        contract = _make_contract()
        json_str = contract.model_dump_json()
        direct = BehaviorContract.model_validate_json(json_str)
        via_helper = parse_contract(json_str)
        assert direct == via_helper == contract


class TestParseContractInvalidJSON:
    """Validates: Requirements 16.4"""

    def test_malformed_json_raises_contract_parse_error(self) -> None:
        """Completely invalid JSON raises ContractParseError."""
        with pytest.raises(ContractParseError):
            parse_contract("{not valid json at all")

    def test_empty_string_raises_contract_parse_error(self) -> None:
        """Empty string raises ContractParseError."""
        with pytest.raises(ContractParseError):
            parse_contract("")

    def test_missing_required_field_raises_with_message(self) -> None:
        """JSON missing 'evidence' raises ContractParseError with descriptive message."""
        # Valid JSON but missing the required 'evidence' field
        json_str = '{"schema_version": 2, "rules": []}'
        with pytest.raises(ContractParseError, match="evidence"):
            parse_contract(json_str)

    def test_wrong_schema_version_raises(self) -> None:
        """schema_version != 2 raises ContractParseError."""
        json_str = (
            '{"schema_version": 1, "evidence": {"generated_from": '
            '{"trajectory_count": 1}}, "rules": []}'
        )
        with pytest.raises(ContractParseError):
            parse_contract(json_str)

    def test_invalid_rule_category_raises_with_message(self) -> None:
        """Invalid category in a rule raises with descriptive message."""
        json_str = (
            '{"schema_version": 2, "evidence": {"generated_from": '
            '{"trajectory_count": 1}}, "rules": [{"id": "rule_001", '
            '"category": "nonexistent", "kind": "test", "target": {}, '
            '"constraint": {}, "cardinality": "all", '
            '"metadata": {"confidence": "high", "support": 1}}]}'
        )
        with pytest.raises(ContractParseError, match="category"):
            parse_contract(json_str)
