"""Point-in-time whale and market microstructure covariate normalization & institutional flow models.

Enforces `UNIVERSAL_AI_ECOSYSTEM.md` rules:
- Records both event_time AND availability_time (`available_at >= event_time + publication_delay`).
- Enforces attribution confidence, finality/reorg confirmation policy, internal custody
  reshuffle exclusions, unit normalization, deduplication, and asset-class validity.
- Rejects on-chain wallet/whale features for non-crypto instruments (e.g. Equity, ETF, Forex).
- Implements causal institutional flow models (`execution_permission = "none"`):
  1. Kyle's Lambda (rolling OLS price impact of informed trading)
  2. VPIN (Volume-Synchronized Probability of Informed Trading via volume bucketing)
  3. Multi-Level Order Flow Imbalance (OFI across L2/L3 depth levels)
  4. Hawkes Self-Exciting Intensity Process for algorithmic child-order & iceberg detection
"""
from __future__ import annotations

import math
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


# ============================================================================
# TASK 1: INSTITUTIONAL FLOW & TOXICITY MODELS (KYLE'S LAMBDA, VPIN, OFI, HAWKES)
# ============================================================================


class KylesLambdaResult(Record):
    """Rolling OLS estimate of Kyle's Lambda: Delta P_t = lambda * Q_t + eta_t."""

    lambda_impact: FiniteFloat
    covariance_dp_q: FiniteFloat
    variance_q: FiniteFloat
    r_squared: Probability
    residual_volatility_eta: FiniteFloat
    sample_count: int = Field(ge=2)
    informed_spike_detected: bool
    execution_permission: Literal["none"] = "none"


def estimate_kyles_lambda(
    price_changes: tuple[float, ...] | list[float],
    signed_order_flows: tuple[float, ...] | list[float],
    *,
    spike_threshold: float = 0.0025,
) -> KylesLambdaResult:
    """Estimate Kyle's Lambda via Cov(Delta P, Q) / Var(Q) over a causal window."""
    if len(price_changes) != len(signed_order_flows):
        raise ValueError("price_changes and signed_order_flows must have identical length")
    n = len(price_changes)
    if n < 2:
        raise ValueError("At least 2 observations are required to estimate Kyle's Lambda")

    mean_dp = sum(price_changes) / n
    mean_q = sum(signed_order_flows) / n

    cov_dp_q = sum((price_changes[i] - mean_dp) * (signed_order_flows[i] - mean_q) for i in range(n)) / n
    var_q = sum((signed_order_flows[i] - mean_q) ** 2 for i in range(n)) / n
    if var_q <= 1e-15:
        raise ValueError("signed_order_flows must have non-zero variance")

    lam = cov_dp_q / var_q
    intercept = mean_dp - lam * mean_q
    residuals = [price_changes[i] - (intercept + lam * signed_order_flows[i]) for i in range(n)]
    sse = sum(r * r for r in residuals)
    sst = sum((price_changes[i] - mean_dp) ** 2 for i in range(n))
    r_sq = max(0.0, min(1.0, 1.0 - (sse / sst))) if sst > 1e-15 else 0.0
    eta_std = math.sqrt(sse / n)

    return KylesLambdaResult(
        lambda_impact=round(lam, 8),
        covariance_dp_q=round(cov_dp_q, 8),
        variance_q=round(var_q, 8),
        r_squared=round(r_sq, 6),
        residual_volatility_eta=round(eta_std, 8),
        sample_count=n,
        informed_spike_detected=abs(lam) >= spike_threshold,
    )


class VpinBucketSlice(Record):
    """Single volume-synchronized bucket tau with buy/sell partitioned volume."""

    bucket_index: int = Field(ge=1)
    buy_volume: FiniteFloat = Field(ge=0)
    sell_volume: FiniteFloat = Field(ge=0)
    abs_imbalance: FiniteFloat = Field(ge=0)


class VpinBucketReport(Record):
    """Volume-Synchronized Probability of Informed Trading (VPIN) report."""

    vpin: Probability
    bucket_volume_v: FiniteFloat = Field(gt=0)
    num_buckets_n: int = Field(ge=1)
    buckets: tuple[VpinBucketSlice, ...]
    toxicity_alert: bool
    recommended_routing: Literal["a_book_exhaust", "b_book_internal"]
    execution_permission: Literal["none"] = "none"


def compute_volume_synchronized_vpin(
    price_deltas: tuple[float, ...] | list[float],
    trade_volumes: tuple[float, ...] | list[float],
    *,
    bucket_volume: float,
    max_buckets: int = 20,
    toxicity_threshold: float = 0.45,
) -> VpinBucketReport:
    """Compute VPIN = sum_{tau=1}^N |V_tau^B - V_tau^S| / (N * V) using volume-synchronized buckets."""
    if len(price_deltas) != len(trade_volumes) or len(trade_volumes) == 0:
        raise ValueError("price_deltas and trade_volumes must be non-empty and of equal length")
    if bucket_volume <= 0:
        raise ValueError("bucket_volume V must be strictly positive")

    # Estimate sigma_dp for Bulk Volume Classification (BVC) or direct tick sign partitioning
    n_trades = len(price_deltas)
    mean_dp = sum(price_deltas) / n_trades
    std_dp = math.sqrt(sum((dp - mean_dp) ** 2 for dp in price_deltas) / max(1, n_trades))

    completed_buckets: list[VpinBucketSlice] = []
    cur_buy = 0.0
    cur_sell = 0.0
    cur_filled = 0.0

    for dp, vol in zip(price_deltas, trade_volumes):
        if vol <= 0:
            continue
        # Smooth normal CDF approximation via erf for BVC buy fraction
        if std_dp > 1e-12:
            z = dp / std_dp
            buy_frac = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        else:
            buy_frac = 1.0 if dp > 0 else (0.0 if dp < 0 else 0.5)

        rem_vol = float(vol)
        while rem_vol > 1e-12:
            space = bucket_volume - cur_filled
            take = min(rem_vol, space)
            cur_buy += take * buy_frac
            cur_sell += take * (1.0 - buy_frac)
            cur_filled += take
            rem_vol -= take

            if abs(cur_filled - bucket_volume) <= 1e-9:
                idx = len(completed_buckets) + 1
                completed_buckets.append(
                    VpinBucketSlice(
                        bucket_index=idx,
                        buy_volume=round(cur_buy, 6),
                        sell_volume=round(cur_sell, 6),
                        abs_imbalance=round(abs(cur_buy - cur_sell), 6),
                    )
                )
                cur_buy = 0.0
                cur_sell = 0.0
                cur_filled = 0.0

    if not completed_buckets:
        raise ValueError("Insufficient cumulative trade volume to fill at least one volume bucket V")

    window = completed_buckets[-max_buckets:]
    n_buckets = len(window)
    total_imbalance = sum(b.abs_imbalance for b in window)
    vpin_val = max(0.0, min(1.0, total_imbalance / (n_buckets * bucket_volume)))
    toxic = vpin_val >= toxicity_threshold

    return VpinBucketReport(
        vpin=round(vpin_val, 6),
        bucket_volume_v=bucket_volume,
        num_buckets_n=n_buckets,
        buckets=tuple(window),
        toxicity_alert=toxic,
        recommended_routing="a_book_exhaust" if toxic else "b_book_internal",
    )


class BookLevelSnapshot(Record):
    """Single L2/L3 orderbook depth level k with bid/ask prices and queue sizes."""

    level: int = Field(ge=1)
    bid_price: FiniteFloat = Field(gt=0)
    bid_size: FiniteFloat = Field(ge=0)
    ask_price: FiniteFloat = Field(gt=0)
    ask_size: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def valid_spread(self) -> Self:
        if self.ask_price <= self.bid_price:
            raise ValueError("ask_price must be strictly greater than bid_price")
        return self


class MultiLevelOfiReport(Record):
    """Multi-Level Order Flow Imbalance (OFI) report across K depth levels."""

    ofi_raw: FiniteFloat
    ofi_normalized: FiniteFloat
    level_contributions: tuple[FiniteFloat, ...]
    weights: tuple[FiniteFloat, ...]
    dominant_pressure: Literal["buy", "sell", "neutral"]
    execution_permission: Literal["none"] = "none"


def compute_multilevel_ofi(
    prev_book: tuple[BookLevelSnapshot, ...] | list[BookLevelSnapshot],
    curr_book: tuple[BookLevelSnapshot, ...] | list[BookLevelSnapshot],
    *,
    decay_lambda: float = 0.65,
) -> MultiLevelOfiReport:
    """Compute depth-weighted multi-level OFI:
    OFI_t = sum_{k=1}^K w_k * [ I(P_k^b >= P_{k,t-1}^b) Delta q_k^b - I(P_k^a <= P_{k,t-1}^a) Delta q_k^a ].
    """
    if len(prev_book) != len(curr_book) or len(curr_book) == 0:
        raise ValueError("prev_book and curr_book must be non-empty and have identical level count K")
    if not (0.0 < decay_lambda <= 1.0):
        raise ValueError("decay_lambda must be in (0, 1]")

    k_levels = len(curr_book)
    raw_weights = [decay_lambda ** (k - 1) for k in range(1, k_levels + 1)]
    w_sum = sum(raw_weights)
    weights = [round(w / w_sum, 6) for w in raw_weights]

    contributions: list[float] = []
    abs_capacity = 0.0

    for k in range(k_levels):
        prev_lvl = prev_book[k]
        curr_lvl = curr_book[k]
        w_k = weights[k]

        # Bid queue reinforcement / depletion
        if curr_lvl.bid_price > prev_lvl.bid_price:
            delta_q_b = curr_lvl.bid_size
        elif curr_lvl.bid_price == prev_lvl.bid_price:
            delta_q_b = curr_lvl.bid_size - prev_lvl.bid_size
        else:
            delta_q_b = -prev_lvl.bid_size

        # Ask queue reinforcement / depletion
        if curr_lvl.ask_price < prev_lvl.ask_price:
            delta_q_a = curr_lvl.ask_size
        elif curr_lvl.ask_price == prev_lvl.ask_price:
            delta_q_a = curr_lvl.ask_size - prev_lvl.ask_size
        else:
            delta_q_a = -prev_lvl.ask_size

        ind_b = 1.0 if curr_lvl.bid_price >= prev_lvl.bid_price else 0.0
        ind_a = 1.0 if curr_lvl.ask_price <= prev_lvl.ask_price else 0.0

        ofi_k = w_k * (ind_b * delta_q_b - ind_a * delta_q_a)
        contributions.append(round(ofi_k, 6))
        abs_capacity += w_k * (abs(delta_q_b) + abs(delta_q_a) + prev_lvl.bid_size + prev_lvl.ask_size)

    ofi_total = sum(contributions)
    ofi_norm = max(-1.0, min(1.0, ofi_total / abs_capacity)) if abs_capacity > 1e-12 else 0.0
    pressure: Literal["buy", "sell", "neutral"] = (
        "buy" if ofi_norm > 0.05 else ("sell" if ofi_norm < -0.05 else "neutral")
    )

    return MultiLevelOfiReport(
        ofi_raw=round(ofi_total, 6),
        ofi_normalized=round(ofi_norm, 6),
        level_contributions=tuple(contributions),
        weights=tuple(weights),
        dominant_pressure=pressure,
    )


class HawkesIntensityReport(Record):
    """Hawkes Self-Exciting Point Process Intensity report for child-order & iceberg detection."""

    intensity_lambda_t: FiniteFloat = Field(ge=0)
    baseline_mu_0: FiniteFloat = Field(gt=0)
    excitation_alpha: FiniteFloat = Field(ge=0)
    decay_beta: FiniteFloat = Field(gt=0)
    branching_ratio: FiniteFloat = Field(ge=0)
    event_count: int = Field(ge=0)
    iceberg_clustering_detected: bool
    stationarity_valid: bool
    execution_permission: Literal["none"] = "none"


def compute_hawkes_intensity(
    event_times_sec: tuple[float, ...] | list[float],
    *,
    eval_time_sec: float,
    mu_0: float = 0.50,
    alpha: float = 0.80,
    beta: float = 1.20,
    clustering_threshold: float = 1.50,
) -> HawkesIntensityReport:
    """Compute causal Hawkes process intensity:
    lambda(t) = mu_0 + sum_{t_i < t} alpha * exp(-beta * (t - t_i)).
    Strictly filters to causal events t_i < eval_time_sec (zero lookahead).
    """
    if mu_0 <= 0 or alpha < 0 or beta <= 0:
        raise ValueError("Hawkes parameters must satisfy mu_0 > 0, alpha >= 0, beta > 0")

    causal_events = [t_i for t_i in event_times_sec if t_i < eval_time_sec]
    excitation = sum(alpha * math.exp(-beta * (eval_time_sec - t_i)) for t_i in causal_events)
    lam_t = mu_0 + excitation
    branching = alpha / beta

    return HawkesIntensityReport(
        intensity_lambda_t=round(lam_t, 6),
        baseline_mu_0=mu_0,
        excitation_alpha=alpha,
        decay_beta=beta,
        branching_ratio=round(branching, 6),
        event_count=len(causal_events),
        iceberg_clustering_detected=(lam_t >= clustering_threshold) or (branching >= 0.75 and len(causal_events) >= 3),
        stationarity_valid=branching < 1.0,
    )


