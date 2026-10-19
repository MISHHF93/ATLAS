"""Deterministic data-quality, provenance, license, and freshness validator."""
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from atlas.models.schemas import Instrument, MarketDataBatch, Record, Text


class DataQualityReport(Record):
    request_id: Text
    instrument_id: Text
    provider_id: Text
    evaluated_at: AwareDatetime
    quality_status: Literal["verified", "unknown", "rejected"]
    freshness_age_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    is_fresh: bool
    license_valid_for_use: bool
    calendar_matched: bool
    point_in_time_valid: bool
    blocking_issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    execution_permission: Literal["none"] = "none"


def validate_market_data_batch(
    batch: MarketDataBatch,
    instrument: Instrument,
    *,
    as_of: datetime,
    max_data_age_seconds: float,
    intended_use: Literal["discovery", "retention", "training", "competition"] = "discovery",
) -> tuple[MarketDataBatch, DataQualityReport]:
    """Validate provenance, license, chronology, calendar, and freshness."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if max_data_age_seconds <= 0:
        raise ValueError("max_data_age_seconds must be positive")

    issues: list[str] = []
    warnings: list[str] = []
    prov = batch.provenance

    # 1. Instrument and calendar match
    calendar_matched = (
        prov.instrument_id == instrument.instrument_id
        and prov.calendar_ref == instrument.calendar_ref
    )
    if not calendar_matched:
        issues.append("calendar_or_instrument_mismatch")

    # 2. Adjustment lineage
    if prov.adjustment_basis == "unknown":
        issues.append("unknown_adjustment_basis")

    # 3. Source and license gates (including Decision #29 FRED prohibition)
    source_lower = f"{prov.provider_id} {prov.source_ref} {prov.license_ref}".lower()
    if "fred" in source_lower and intended_use in {"retention", "training", "competition"}:
        issues.append("fred_terms_prohibit_ai_training_and_archival")

    license_valid = True
    if prov.license_ref.strip().lower() in {"unknown", "unlicensed", "none"}:
        license_valid = False
        issues.append("missing_or_unverified_license_ref")
    if intended_use == "retention" and not prov.allow_retention:
        license_valid = False
        issues.append("license_disallows_retention")
    elif intended_use == "training" and not (prov.allow_retention and prov.allow_training):
        license_valid = False
        issues.append("license_disallows_training")
    elif intended_use == "competition" and not (prov.allow_retention and prov.allow_competition):
        license_valid = False
        issues.append("license_disallows_competition")

    # 4. Point-in-time availability
    pit_valid = True
    if prov.retrieved_at > as_of:
        pit_valid = False
        issues.append("provenance_retrieved_after_as_of")
    for obs in (*batch.observations, *batch.features):
        if obs.available_at > as_of:
            pit_valid = False
            issues.append("future_information_leakage_detected")
            break

    # 5. Observations presence & freshness
    age_seconds: float | None = None
    is_fresh = False
    if not batch.observations:
        issues.append("empty_observations")
    else:
        latest_event = batch.observations[-1].event_time
        age_seconds = max(0.0, (as_of - latest_event).total_seconds())
        is_fresh = age_seconds <= max_data_age_seconds
        if not is_fresh:
            issues.append("stale_observations_exceed_max_data_age")

    if any(f.quality != "verified" for f in batch.features):
        warnings.append("unverified_covariate_features_present")

    if issues:
        # Distinguish hard rejection (leakage/FRED/mismatch) vs unknown metadata
        hard_reject_tokens = (
            "future_information",
            "fred_terms",
            "mismatch",
            "license_disallows",
        )
        status: Literal["verified", "unknown", "rejected"] = (
            "rejected"
            if any(any(tok in issue for tok in hard_reject_tokens) for issue in issues)
            else "unknown"
        )
    else:
        status = "verified"

    updated_batch = batch.model_copy(update={"quality": status})
    report = DataQualityReport(
        request_id=batch.request_id,
        instrument_id=instrument.instrument_id,
        provider_id=prov.provider_id,
        evaluated_at=as_of,
        quality_status=status,
        freshness_age_seconds=age_seconds,
        is_fresh=is_fresh,
        license_valid_for_use=license_valid,
        calendar_matched=calendar_matched,
        point_in_time_valid=pit_valid,
        blocking_issues=tuple(issues),
        warnings=tuple(warnings),
    )
    return updated_batch, report

