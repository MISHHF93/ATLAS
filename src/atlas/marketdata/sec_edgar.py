"""Point-in-time SEC EDGAR as-filed XBRL/submission adapter.

Enforces `RESEARCH_OPERATING_CONTRACT.md` Gate #2 and `MCP_DATA_INTEGRATION.md`:
- Requires a descriptive contact User-Agent header (`Name AdminContact@domain.com`).
- Enforces SEC rate limits (`<= 10 requests/second`) through `ProviderRuntime`.
- Separates `fiscal_period_end` from SEC `acceptance_time` (`available_at`).
- Selects only facts accepted at or before `as_of`, excluding later amendments (`10-K/A`,
  `10-Q/A`) or restatements filed after `as_of` to prevent lookahead leakage.
- All outputs are research records with `execution_permission: none`.
"""
from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, FiniteFloat, model_validator

from atlas.models.schemas import FeatureValue, Record, Text


class SECEdgarFilingFact(Record):
    accession_number: Text
    cik: Text
    instrument_id: Text
    form_type: Literal["10-K", "10-Q", "8-K", "10-K/A", "10-Q/A"]
    concept: Text
    value: FiniteFloat
    unit: Text
    fiscal_period_end: AwareDatetime
    acceptance_time: AwareDatetime
    is_amendment: bool = False

    @model_validator(mode="after")
    def acceptance_follows_period(self) -> Self:
        if self.acceptance_time < self.fiscal_period_end:
            raise ValueError("SEC filing acceptance_time cannot precede fiscal_period_end")
        if self.form_type.endswith("/A") and not self.is_amendment:
            raise ValueError("Amended SEC forms (/A) must set is_amendment=True")
        return self


def validate_sec_user_agent(user_agent: str) -> str:
    """SEC EDGAR requires a descriptive User-Agent with contact email (`AppName contact@domain`)."""
    cleaned = user_agent.strip()
    if len(cleaned) < 10 or "@" not in cleaned or " " not in cleaned:
        raise ValueError(
            "SEC EDGAR requires a descriptive User-Agent with contact email (e.g. 'ATLASResearch ops@example.com')"
        )
    return cleaned


def select_as_filed_sec_facts(
    facts: tuple[SECEdgarFilingFact, ...],
    *,
    instrument_id: str,
    as_of: datetime,
    allow_vintage_amendments: bool = False,
) -> tuple[FeatureValue, ...]:
    """Filter SEC XBRL facts strictly by acceptance_time <= as_of, excluding later restatements."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    eligible: dict[tuple[str, datetime], SECEdgarFilingFact] = {}
    for fact in sorted(facts, key=lambda item: item.acceptance_time):
        if fact.instrument_id != instrument_id:
            raise ValueError("SEC filing fact instrument_id mismatch")
        # Exclude any filing accepted after as_of (prevents restatement/filing lookahead)
        if fact.acceptance_time > as_of:
            continue
        if fact.is_amendment and not allow_vintage_amendments:
            continue
        key = (fact.concept, fact.fiscal_period_end)
        # If allow_vintage_amendments is False, keep original as-filed fact; else latest accepted by as_of
        if key not in eligible or allow_vintage_amendments:
            eligible[key] = fact

    features = [
        FeatureValue(
            name=f"sec_xbrl:{fact.concept}",
            source=f"sec_edgar:{fact.form_type}",
            lineage_ref=f"cik:{fact.cik}|acc:{fact.accession_number}|period:{fact.fiscal_period_end.date().isoformat()}",
            license_ref="sec_edgar:public_domain_reuse",
            quality="verified",
            event_time=fact.fiscal_period_end,
            available_at=fact.acceptance_time,
            value=fact.value,
        )
        for fact in eligible.values()
    ]
    features.sort(key=lambda item: (item.available_at, item.name))
    return tuple(features)
