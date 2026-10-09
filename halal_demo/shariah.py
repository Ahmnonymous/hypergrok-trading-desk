"""Deterministic Shariah gate.

Outcomes are PASS, REJECT, or REQUIRES_HUMAN_REVIEW. Only PASS can continue.
This module does not issue a religious ruling and does not apply a debt,
cash, or income ratio. Those stay unresolved until a policy file records an
adviser decision. Agents cannot call a bypass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from halal_demo.clock import parse_utc
from halal_demo.config import require_text
from halal_demo.errors import ConfigError

PASS = "PASS"
REJECT = "REJECT"
REVIEW = "REQUIRES_HUMAN_REVIEW"

# Build rules from the project brief. A policy file cannot soften them.
STRUCTURAL_REJECT_TYPES = frozenset(
    {
        "cfd",
        "futures",
        "perpetual",
        "margin",
        "swap",
        "interest_bearing",
        "lending",
        "option",
        "leveraged_forex",
        "leveraged",
    }
)


@dataclass(frozen=True)
class ApprovalRecord:
    instrument: str
    asset_class: str
    venue: str
    contract_type: str
    ownership: str
    settlement: str
    business_activity: str | None
    financial_screen_decision: str | None
    gold_structure_accepted: bool
    evidence_note: str


@dataclass(frozen=True)
class ShariahPolicy:
    rule_version: str
    reviewer: str
    review_date: str
    expiry: datetime
    evidence_source: str
    decision_status: str
    offline_test_only: bool
    accepted_ownership: tuple[str, ...]
    accepted_settlement: tuple[str, ...]
    accepted_business_activities: tuple[str, ...]
    prohibited_business_activities: tuple[str, ...]
    prohibited_instruments: tuple[str, ...]
    crypto_eligibility: dict[str, str]
    approvals: tuple[ApprovalRecord, ...]
    stock_financial_criteria: dict | None

    @classmethod
    def from_dict(cls, data: dict) -> "ShariahPolicy":
        errors: list[str] = []
        rule_version = require_text(data, "rule_version", errors)
        reviewer = require_text(data, "reviewer", errors)
        review_date = require_text(data, "review_date", errors)
        evidence_source = require_text(data, "evidence_source", errors)
        decision_status = require_text(data, "decision_status", errors)
        if decision_status not in {
            "unresolved",
            "recorded_for_offline_test_only",
            "adviser_signed",
        }:
            errors.append("invalid:decision_status")
        expiry = None
        if isinstance(data.get("expiry"), str):
            try:
                expiry = parse_utc(data["expiry"], "expiry")
            except ValueError:
                errors.append("invalid:expiry")
        else:
            errors.append("missing:expiry")
        offline = data.get("offline_test_only", False)
        if not isinstance(offline, bool):
            errors.append("invalid:offline_test_only")
            offline = False
        if decision_status == "recorded_for_offline_test_only" and offline is not True:
            errors.append("offline test policy must set offline_test_only true")
        if decision_status == "adviser_signed" and offline is True:
            errors.append("adviser_signed policy cannot also be an offline test fixture")
        approvals = []
        raw_approvals = data.get("approvals", [])
        if not isinstance(raw_approvals, list):
            errors.append("invalid:approvals")
            raw_approvals = []
        for index, row in enumerate(raw_approvals):
            if not isinstance(row, dict):
                errors.append(f"invalid:approvals[{index}]")
                continue
            approvals.append(_approval(row, index, errors))
        criteria = data.get("stock_financial_criteria")
        if criteria not in (None, {}):
            # Numeric screens are stored only so a human can see them.
            # This engine does not turn a ratio into PASS.
            if not isinstance(criteria, dict):
                errors.append("invalid:stock_financial_criteria")
                criteria = None
        accepted_ownership = _strings(data.get("accepted_ownership"), "accepted_ownership", errors)
        accepted_settlement = _strings(data.get("accepted_settlement"), "accepted_settlement", errors)
        accepted_business = _strings(
            data.get("accepted_business_activities"), "accepted_business_activities", errors
        )
        prohibited_business = _strings(
            data.get("prohibited_business_activities"), "prohibited_business_activities", errors
        )
        prohibited_instruments = _strings(
            data.get("prohibited_instruments"), "prohibited_instruments", errors
        )
        crypto = _crypto_map(data.get("crypto_eligibility"), errors)
        if errors:
            raise ConfigError(errors)
        assert expiry is not None
        return cls(
            rule_version=rule_version,
            reviewer=reviewer,
            review_date=review_date,
            expiry=expiry,
            evidence_source=evidence_source,
            decision_status=decision_status,
            offline_test_only=offline,
            accepted_ownership=tuple(accepted_ownership),
            accepted_settlement=tuple(accepted_settlement),
            accepted_business_activities=tuple(accepted_business),
            prohibited_business_activities=tuple(prohibited_business),
            prohibited_instruments=tuple(prohibited_instruments),
            crypto_eligibility=crypto,
            approvals=tuple(approvals),
            stock_financial_criteria=criteria if isinstance(criteria, dict) and criteria else None,
        )


def _strings(value: object, field: str, errors: list[str]) -> list[str]:
    if value is None:
        errors.append(f"missing:{field}")
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        errors.append(f"invalid:{field}")
        return []
    return [item.strip() for item in value]


def _crypto_map(value: object, errors: list[str]) -> dict[str, str]:
    if value is None:
        errors.append("missing:crypto_eligibility")
        return {}
    if not isinstance(value, list):
        errors.append("invalid:crypto_eligibility")
        return {}
    found: dict[str, str] = {}
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            errors.append(f"invalid:crypto_eligibility[{index}]")
            continue
        symbol = row.get("instrument")
        decision = row.get("decision")
        contract = row.get("contract_type")
        if not all(isinstance(item, str) and item.strip() for item in (symbol, decision, contract)):
            errors.append(f"incomplete:crypto_eligibility[{index}]")
            continue
        if contract != "spot":
            errors.append(f"crypto_eligibility[{index}] must be spot")
            continue
        if decision not in {"eligible", "ineligible", "not_reviewed"}:
            errors.append(f"invalid crypto decision at [{index}]")
            continue
        found[symbol.strip().upper()] = decision
    return found


def _approval(row: dict, index: int, errors: list[str]) -> ApprovalRecord:
    def text(field: str, required: bool = True) -> str | None:
        value = row.get(field)
        if value in (None, ""):
            if required:
                errors.append(f"incomplete:approvals[{index}].{field}")
            return None
        if not isinstance(value, str) or not value.strip():
            errors.append(f"invalid:approvals[{index}].{field}")
            return None
        return value.strip()

    gold_flag = row.get("gold_structure_accepted", False)
    if not isinstance(gold_flag, bool):
        errors.append(f"invalid:approvals[{index}].gold_structure_accepted")
        gold_flag = False
    return ApprovalRecord(
        instrument=text("instrument") or "",
        asset_class=text("asset_class") or "",
        venue=text("venue") or "",
        contract_type=text("contract_type") or "",
        ownership=text("ownership") or "",
        settlement=text("settlement") or "",
        business_activity=text("business_activity", required=False),
        financial_screen_decision=text("financial_screen_decision", required=False),
        gold_structure_accepted=gold_flag,
        evidence_note=text("evidence_note") or "",
    )


@dataclass(frozen=True)
class InstrumentFacts:
    """Facts observed by an adapter. Proposal text is not a source of facts."""

    instrument: str
    asset_class: str
    venue: str
    contract_type: str
    leverage_class: str
    swap_state: str
    interest_bearing: str
    ownership: str | None
    settlement: str | None
    business_activity: str | None
    business_activity_verified: bool
    financials_verified: bool
    data_verified: bool
    market_data_label: str
    gold_symbol: bool
    contract_structure_identified: bool
    source: str
    quoted_at: datetime | None


@dataclass(frozen=True)
class ShariahDecision:
    status: str
    rule_version: str
    reasons: tuple[str, ...]
    reviewer: str
    review_date: str

    @property
    def passed(self) -> bool:
        return self.status == PASS


def evaluate(
    facts: InstrumentFacts,
    policy: ShariahPolicy,
    now: datetime,
    *,
    allow_offline_test_policy: bool,
) -> ShariahDecision:
    reasons: list[str] = []
    if not facts.data_verified:
        reasons.append("missing_compliance_data:data_not_verified")
    if facts.market_data_label not in {"synthetic", "offline_fixture"}:
        reasons.append("missing_compliance_data:market_data_not_offline")
    if facts.quoted_at is None:
        reasons.append("missing_compliance_data:quote_timestamp")
    structural = _structural_reject(facts)
    if structural:
        reasons.extend(structural)
        return _decision(REJECT, policy, reasons)
    if policy.expiry <= now:
        reasons.append("policy_expired")
        return _decision(REVIEW, policy, reasons)
    if not policy.rule_version or not policy.reviewer or not policy.evidence_source:
        reasons.append("missing_compliance_data:policy_identity")
        return _decision(REVIEW, policy, reasons)
    if facts.instrument.upper() in {item.upper() for item in policy.prohibited_instruments}:
        reasons.append("prohibited_instrument")
        return _decision(REJECT, policy, reasons)
    if facts.business_activity and facts.business_activity in policy.prohibited_business_activities:
        reasons.append("prohibited_business_activity")
        return _decision(REJECT, policy, reasons)
    crypto = _crypto_gate(facts, policy, reasons)
    if crypto == REJECT:
        return _decision(REJECT, policy, reasons)
    if facts.gold_symbol:
        gold = _gold_gate(facts, policy, reasons)
        if gold is not None:
            return _decision(gold, policy, reasons)
    if reasons:
        return _decision(REVIEW, policy, reasons)
    if not _status_allows_pass(policy, allow_offline_test_policy):
        reasons.append("shariah_status_unresolved")
        return _decision(REVIEW, policy, reasons)
    record = _match(facts, policy)
    if record is None:
        reasons.append("unknown_shariah_status")
        return _decision(REVIEW, policy, reasons)
    if not _record_agrees(facts, record, policy, reasons):
        return _decision(REVIEW, policy, reasons)
    return _decision(PASS, policy, ["approval_record_matched"])


def _structural_reject(facts: InstrumentFacts) -> list[str]:
    reasons = []
    contract = (facts.contract_type or "").strip().lower()
    if contract in STRUCTURAL_REJECT_TYPES:
        reasons.append(f"structural_reject:{contract}")
    if facts.leverage_class == "leveraged":
        reasons.append("structural_reject:leveraged")
    if facts.swap_state == "enabled":
        reasons.append("structural_reject:swap")
    if facts.interest_bearing == "yes":
        reasons.append("structural_reject:interest")
    if not contract or contract == "unknown":
        reasons.append("unknown_contract_type")
    return reasons


def _crypto_gate(facts: InstrumentFacts, policy: ShariahPolicy, reasons: list[str]) -> str | None:
    if facts.asset_class != "crypto":
        return None
    if facts.contract_type.lower() != "spot":
        reasons.append("crypto_not_spot")
        return REJECT
    decision = policy.crypto_eligibility.get(facts.instrument.upper())
    if decision is None:
        reasons.append("crypto_eligibility_missing")
        return REVIEW
    if decision == "ineligible":
        reasons.append("crypto_not_eligible")
        return REJECT
    if decision != "eligible":
        reasons.append("crypto_eligibility_not_reviewed")
        return REVIEW
    return None


def _gold_gate(facts: InstrumentFacts, policy: ShariahPolicy, reasons: list[str]) -> str | None:
    # XAUUSD and other gold symbols are never approved from the name alone.
    if not facts.contract_structure_identified:
        reasons.append("gold_structure_not_identified")
        return REVIEW
    if facts.contract_type != "identified_deliverable_spot":
        reasons.append("gold_structure_not_deliverable_spot")
        return REVIEW
    record = _match(facts, policy)
    if record is None or not record.gold_structure_accepted:
        reasons.append("gold_requires_explicit_structure_acceptance")
        return REVIEW
    return None


def _status_allows_pass(policy: ShariahPolicy, allow_offline_test_policy: bool) -> bool:
    if policy.decision_status == "unresolved":
        return False
    if policy.decision_status == "recorded_for_offline_test_only":
        return bool(policy.offline_test_only and allow_offline_test_policy)
    if policy.decision_status == "adviser_signed":
        return True
    return False


def _match(facts: InstrumentFacts, policy: ShariahPolicy) -> ApprovalRecord | None:
    matches = [
        row
        for row in policy.approvals
        if row.instrument.upper() == facts.instrument.upper()
        and row.asset_class == facts.asset_class
        and row.venue == facts.venue
        and row.contract_type == facts.contract_type
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _record_agrees(
    facts: InstrumentFacts,
    record: ApprovalRecord,
    policy: ShariahPolicy,
    reasons: list[str],
) -> bool:
    ok = True
    if facts.ownership not in policy.accepted_ownership or facts.ownership != record.ownership:
        reasons.append("ownership_not_accepted")
        ok = False
    if facts.settlement not in policy.accepted_settlement or facts.settlement != record.settlement:
        reasons.append("settlement_not_accepted")
        ok = False
    if facts.asset_class == "stock":
        if not facts.business_activity_verified or not facts.business_activity:
            reasons.append("missing_compliance_data:business_activity")
            ok = False
        elif facts.business_activity not in policy.accepted_business_activities:
            reasons.append("business_activity_not_accepted")
            ok = False
        elif record.business_activity != facts.business_activity:
            reasons.append("business_activity_mismatch")
            ok = False
        if not facts.financials_verified:
            reasons.append("missing_compliance_data:financials")
            ok = False
        if record.financial_screen_decision != "recorded":
            reasons.append("financial_screen_not_recorded")
            ok = False
        if policy.stock_financial_criteria:
            # A file of ratios is not a decision. A person still has to record one.
            reasons.append("financial_ratios_require_human_review")
            ok = False
    if facts.leverage_class != "none":
        reasons.append("leverage_not_cleared")
        ok = False
    if facts.swap_state != "disabled":
        reasons.append("swap_not_cleared")
        ok = False
    if facts.interest_bearing != "no":
        reasons.append("interest_not_cleared")
        ok = False
    if facts.gold_symbol and not record.gold_structure_accepted:
        reasons.append("gold_not_explicitly_accepted")
        ok = False
    return ok


def _decision(status: str, policy: ShariahPolicy, reasons: list[str]) -> ShariahDecision:
    if status == PASS and any(not item.startswith("approval_record_matched") for item in reasons):
        status = REVIEW
    return ShariahDecision(
        status=status,
        rule_version=policy.rule_version,
        reasons=tuple(dict.fromkeys(reasons)) or ("unspecified",),
        reviewer=policy.reviewer,
        review_date=policy.review_date,
    )
