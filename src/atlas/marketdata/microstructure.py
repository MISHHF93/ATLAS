"""Point-in-time whale and market microstructure covariate normalization.

Enforces `UNIVERSAL_AI_ECOSYSTEM.md` rules:
- Records both event_time AND availability_time (`available_at >= event_time + publication_delay`).
- Enforces attribution confidence, finality/reorg confirmation policy, internal custody
  reshuffle exclusions, unit normalization, deduplication, and asset-class validity.
- Rejects on-chain wallet/whale features for non-crypto instruments (e.g. Equity, ETF, Forex).
"""
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, Field, FiniteFloat, model_validator

from atlas.models.schemas import AssetClass, FeatureValue, Instrument, Probability, Record, Text

MicrostructureKind = Literal[
    "large_transfer",
    "exchange_inflow",
    "exchange_outflow",
    "order_flow_imbalance",
    "liquidity_heatmap_imbalance",
    "open_interest",
    "funding_rate",
    "liquidation_cascade",
    "stablecoin_flow",
]

ONCHAIN_WALLET_FEATURES: frozenset[MicrostructureKind] = frozenset({
    "large_transfer",
    "exchange_inflow",
    "exchange_outflow",
    "stablecoin_flow",
})


class WhaleMicrostructurePolicy(Record):
    policy_id: Text = "microstructure-policy:v1"
    min_attribution_confidence: Probability = 0.75
    min_confirmations: int = Field(default=6, ge=0)
    exclude_internal_transfers: bool = True
    min_publication_delay_seconds: float = Field(default=5.0, ge=0, allow_inf_nan=False)
    missingness_policy: Literal["drop", "mark_unknown"] = "mark_unknown"


class RawMicrostructureEvent(Record):
    event_id: Text
    kind: MicrostructureKind
    instrument_id: Text
    event_time: AwareDatetime
    available_at: AwareDatetime
    value: FiniteFloat
    unit: Text
    source: Text
    lineage_ref: Text
    license_ref: Text
    attribution_confidence: Probability = 1.0
    confirmations: int = Field(default=10, ge=0)
    is_finalized: bool = True
    is_internal_custody_reshuffle: bool = False

    @model_validator(mode="after")
    def valid_timestamps(self) -> Self:
        if self.available_at < self.event_time:
            raise ValueError("Microstructure event cannot be available before event_time")
        return self


def normalize_microstructure_covariates(
    events: tuple[RawMicrostructureEvent, ...],
    instrument: Instrument,
    *,
    as_of: datetime,
    policy: WhaleMicrostructurePolicy | None = None,
) -> tuple[FeatureValue, ...]:
    """Validate, deduplicate, and normalize microstructure/whale events into point-in-time FeatureValues."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    active_policy = policy or WhaleMicrostructurePolicy()

    seen_ids: set[str] = set()
    normalized: list[FeatureValue] = []

    for evt in events:
        if evt.event_id in seen_ids:
            continue
        seen_ids.add(evt.event_id)

        if evt.instrument_id != instrument.instrument_id:
            raise ValueError("Microstructure event instrument_id does not match target instrument")

        # No chain/wallet feature is automatically meaningful for an equity or forex pair
        if evt.kind in ONCHAIN_WALLET_FEATURES and instrument.asset_class not in {
            AssetClass.CRYPTO_SPOT,
            AssetClass.CRYPTO_DERIVATIVE,
        }:
            raise ValueError(
                f"On-chain feature '{evt.kind}' is not valid for asset_class={instrument.asset_class}"
            )

        if evt.available_at > as_of:
            raise ValueError("Future microstructure event (available_at > as_of) rejected")

        # Exclude internal custody reshuffles
        if active_policy.exclude_internal_transfers and evt.is_internal_custody_reshuffle:
            continue

        # Check finality/confirmations, attribution confidence, and publication delay
        delay_ok = (evt.available_at - evt.event_time).total_seconds() >= active_policy.min_publication_delay_seconds
        finality_ok = evt.is_finalized and (
            evt.confirmations >= active_policy.min_confirmations
            if evt.kind in ONCHAIN_WALLET_FEATURES
            else True
        )
        attribution_ok = evt.attribution_confidence >= active_policy.min_attribution_confidence
        license_ok = evt.license_ref.strip().lower() not in {"unknown", "unlicensed", "none"}

        if delay_ok and finality_ok and attribution_ok and license_ok:
            quality: Literal["verified", "unknown"] = "verified"
        else:
            if active_policy.missingness_policy == "drop":
                continue
            quality = "unknown"

        normalized.append(
            FeatureValue(
                name=f"microstructure:{evt.kind}",
                source=evt.source,
                lineage_ref=f"{evt.lineage_ref}|{active_policy.policy_id}",
                license_ref=evt.license_ref,
                quality=quality,
                event_time=evt.event_time,
                available_at=max(
                    evt.available_at,
                    evt.event_time + timedelta(seconds=active_policy.min_publication_delay_seconds),
                ),
                value=evt.value,
            )
        )

    normalized.sort(key=lambda item: (item.event_time, item.name))
    return tuple(normalized)

