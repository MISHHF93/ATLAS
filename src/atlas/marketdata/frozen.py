"""Frozen point-in-time dataset builder and verifier for competition and open-market tracks."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Literal

from atlas.models.calendars import MarketCalendar
from atlas.models.schemas import DatasetManifest, Instrument, Observation, Record, Text


class FrozenDatasetBundle(Record):
    track: Literal["competition", "open_market"]
    competition_rulebook_ref: Text | None = None
    instrument: Instrument
    calendar: MarketCalendar
    manifest: DatasetManifest
    observations: tuple[Observation, ...]
    serialized_bytes: bytes
    execution_permission: Literal["none"] = "none"


def build_frozen_benchmark_dataset(
    *,
    track: Literal["competition", "open_market"] = "competition",
    anchor: datetime | None = None,
) -> FrozenDatasetBundle:
    """Create a deterministic, point-in-time frozen synthetic dataset with verified SHA-256 manifest.

    Separates competition vs open-market evaluation scopes per `RESEARCH_OPERATING_CONTRACT.md`.
    """
    base_time = anchor or datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    if base_time.tzinfo is None or base_time.utcoffset() is None:
        raise ValueError("anchor must be timezone-aware")

    total_bars = 48
    start_time = base_time - timedelta(hours=total_bars)

    observations: list[Observation] = []
    price = 67000.0 if track == "competition" else 580.0
    for idx in range(total_bars):
        event_ts = start_time + timedelta(hours=idx)
        available_ts = event_ts + timedelta(seconds=5)
        # Deterministic regime-shifting path: low-vol drift -> high-vol breakout -> mean reversion
        if idx < 16:
            step_ret = 0.0015 * math.sin(idx * 0.5) + 0.0008
        elif idx < 32:
            step_ret = 0.0065 * math.cos(idx * 0.7) + 0.0020 * (1 if idx % 2 == 0 else -1)
        else:
            step_ret = 0.0035 * math.sin(idx * 0.4) + 0.0012
        price = round(price * (1.0 + step_ret), 4)
        observations.append(
            Observation(
                event_time=event_ts,
                available_at=available_ts,
                value=price,
            )
        )

    obs_tuple = tuple(observations)
    canonical_payload = [
        {
            "event_time": obs.event_time.isoformat(),
            "available_at": obs.available_at.isoformat(),
            "value": obs.value,
        }
        for obs in obs_tuple
    ]
    raw_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()

    if track == "competition":
        calendar_ref = "crypto:perp:24x7:v1"
        instrument = Instrument(
            instrument_id="comp:btc-perp:v1",
            venue="competition-perp-venue",
            symbol="BTC-PERP",
            asset_class="crypto_derivative",
            base_currency="BTC",
            quote_currency="USD",
            contract_size="1",
            tick_size="0.10",
            lot_size="0.01",
            margin_policy_ref="comp:margin:10x:v1",
            calendar_ref=calendar_ref,
            settlement="USDT-perp",
            market_data=frozenset({"observations", "funding"}),
            permitted_research=True,
        )
        calendar = MarketCalendar(
            calendar_ref=calendar_ref,
            market_type="continuous_crypto",
            timezone="UTC",
            funding_timestamps=(
                base_time - timedelta(hours=8),
                base_time,
                base_time + timedelta(hours=8),
            ),
        )
        dataset_id = "frozen:comp:btc-perp:1h:v1"
        rulebook_ref = "prop-comp-2026-q4:v1"
    else:
        calendar_ref = "us-equity:xnys:v1"
        instrument = Instrument(
            instrument_id="open:spy-etf:v1",
            venue="XNYS",
            symbol="SPY",
            asset_class="etf",
            base_currency="SPY",
            quote_currency="USD",
            contract_size="1",
            tick_size="0.01",
            lot_size="1",
            margin_policy_ref="reg-t:cash:v1",
            calendar_ref=calendar_ref,
            settlement="T+1",
            market_data=frozenset({"observations", "sessions"}),
            permitted_research=True,
        )
        calendar = MarketCalendar(
            calendar_ref=calendar_ref,
            market_type="traditional_session",
            timezone="America/New_York",
            session_targets=(
                base_time - timedelta(days=1),
                base_time + timedelta(days=1),
                base_time + timedelta(days=2),
                base_time + timedelta(days=3),
            ),
            holidays=("2026-11-26", "2026-12-25"),
        )
        dataset_id = "frozen:open:spy-etf:1h:v1"
        rulebook_ref = None

    manifest = DatasetManifest(
        dataset_id=dataset_id,
        content_sha256=digest,
        source_refs=(f"synthetic_frozen:{track}:v1",),
        license_refs=("internal:licensed-research-fixture:v1",),
        feature_lineage=("lag_return_1", "lag_return_2", "rolling_vol_4", "regime_state"),
        transform_revision="pit-features:v1",
        train_end=obs_tuple[23].available_at,
        validation_start=obs_tuple[24].available_at,
        validation_end=obs_tuple[35].available_at,
        test_start=obs_tuple[36].available_at,
        test_end=obs_tuple[47].available_at,
    )
    manifest.verify_content(raw_bytes)

    return FrozenDatasetBundle(
        track=track,
        competition_rulebook_ref=rulebook_ref,
        instrument=instrument,
        calendar=calendar,
        manifest=manifest,
        observations=obs_tuple,
        serialized_bytes=raw_bytes,
    )

