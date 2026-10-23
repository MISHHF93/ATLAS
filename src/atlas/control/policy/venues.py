"""Venue / jurisdiction eligibility (venues.yaml): schema, cross-validation and
the pre-trade eligibility check used by the RiskEngine. Fails closed."""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EntityType = Literal["individual", "corporation", "fund"]


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")


class Registration(_M):
    status: str
    regulator: str
    last_verified: date
    interim_relief: bool = False
    note: str | None = None


class VenueFlags(_M):
    margin: bool = False
    derivatives: bool = False
    spot_only: bool = False


class Venue(_M):
    legal_entity: str
    entity_types: list[EntityType]
    registration: Registration
    execution_allowed: bool
    paper_only: bool = False
    asset_classes: list[str]
    flags: VenueFlags
    asset_blocklist: list[str] = []
    asset_blocklist_file: str | None = None


class OperatingEntity(_M):
    id: str
    type: EntityType
    province: str
    data_licence: Literal["non_pro", "pro"]


class DataProvider(_M):
    markets: list[str]
    tsx: bool
    plans: dict[str, str]


class VenuesCfg(_M):
    version: int
    verification_max_age_days: int = Field(gt=0, le=365)
    operating_entity: OperatingEntity
    venues: dict[str, Venue]
    excluded_venues: dict[str, str]
    registered_statuses: list[str]
    data_providers: dict[str, DataProvider]
    data_routes: dict[str, object]


def as_of_date() -> date:
    """Validation date. ATLAS_AS_OF (YYYY-MM-DD) pins it for reproducible tests."""
    v = os.environ.get("ATLAS_AS_OF")
    return date.fromisoformat(v) if v else date.today()


def registration_problem(v: Venue, cfg: VenuesCfg, today: date) -> str | None:
    r = v.registration
    if v.paper_only:
        return None  # paper simulator only; registration irrelevant (live impossible in this build anyway)
    if r.status not in cfg.registered_statuses:
        return f"registration status {r.status!r} not in {cfg.registered_statuses}"
    age = (today - r.last_verified).days
    if age < 0:
        return f"last_verified {r.last_verified} is in the future"
    if age > cfg.verification_max_age_days:
        return f"registration last verified {age} days ago (> {cfg.verification_max_age_days}) - re-verify"
    return None


def validate_venues(vc: VenuesCfg, enabled_brokers: list[str], today: date | None = None) -> list[str]:
    today = today or as_of_date()
    errs: list[str] = []
    ent = vc.operating_entity
    for b in enabled_brokers:
        v = vc.venues.get(b)
        if v is None:
            errs.append(f"venues: enabled broker {b!r} has no eligibility entry"); continue
        if b in vc.excluded_venues:
            errs.append(f"venues: broker {b!r} is an excluded venue")
        if not v.execution_allowed:
            errs.append(f"venues: {b!r} enabled in brokers.yaml but execution_allowed=false")
        if ent.type not in v.entity_types:
            errs.append(f"venues: {b!r} not available to entity type {ent.type!r}")
        p = registration_problem(v, vc, today)
        if p:
            errs.append(f"venues: {b!r} {p}")
        if v.flags.margin or v.flags.derivatives:
            errs.append(f"venues: {b!r} margin/derivatives flags must be false in this build")
    for name in vc.excluded_venues:
        base = name.removesuffix("_live")
        if base in vc.venues and vc.venues[base].execution_allowed and not vc.venues[base].paper_only:
            errs.append(f"venues: {base!r} is excluded ({name}) but allowed for live-capable execution")
    # data licensing
    routes = vc.data_routes
    licences = routes.get("licences", {}) if isinstance(routes, dict) else {}
    for prov, lic in (licences or {}).items():
        dp = vc.data_providers.get(prov)
        if dp is None:
            errs.append(f"data: unknown provider {prov!r}"); continue
        needed = dp.plans.get(ent.type)
        if needed and needed != lic:
            errs.append(f"data: {prov} licence {lic!r} invalid for {ent.type} (needs {needed!r})")
        if ent.type != "individual" and lic == "non_pro":
            errs.append(f"data: {prov} non_pro licence cannot be used by a {ent.type}")
    for prov in routes.get("ca_equity", []) if isinstance(routes, dict) else []:
        dp = vc.data_providers.get(prov)
        if dp is None or not dp.tsx:
            errs.append(f"data: ca_equity routed to {prov!r} which has no TSX coverage (use ibkr_data/tmx)")
    if ent.type != "individual" and ent.data_licence == "non_pro":
        errs.append(f"data: operating entity {ent.type} must use pro/commercial data licences")
    return errs


_SPLIT = re.compile(r"[-/_:]")


def symbol_assets(symbol: str) -> set[str]:
    parts = {p.upper() for p in _SPLIT.split(symbol) if p}
    if len(parts) == 1 and len(symbol) in (6, 7, 8):  # e.g. USDTCAD / XBTUSDT
        s = symbol.upper()
        for q in ("USDT", "USDC", "USDG", "CAD", "USD", "EUR"):
            if s.endswith(q):
                parts |= {s[: -len(q)], q}
    return parts


class EligibilityHook:
    """RiskEngine pre-trade hook: returns (failures, warnings)."""
    name = "venue_eligibility"

    def __init__(self, vc: VenuesCfg, today=as_of_date):
        self.vc = vc
        self.today = today

    def __call__(self, intent, state) -> tuple[list[str], list[str]]:
        fails, warns = [], []
        v = self.vc.venues.get(intent.broker)
        if v is None or intent.broker in self.vc.excluded_venues:
            return [f"venue {intent.broker!r} not eligible / excluded"], warns
        ent = self.vc.operating_entity
        if not v.execution_allowed:
            fails.append(f"execution not allowed at {intent.broker}")
        if ent.type not in v.entity_types:
            fails.append(f"{intent.broker} not available to {ent.type}")
        p = registration_problem(v, self.vc, self.today())
        if p:
            fails.append(f"{intent.broker}: {p}")
        if v.asset_classes and intent.asset_class not in v.asset_classes:
            fails.append(f"{intent.asset_class} not allowed at {intent.broker} (allowed {v.asset_classes})")
        if v.flags.spot_only and intent.asset_class not in ("crypto_spot", "fx_spot", "equity", "etf", "index_etf", "us_equity", "ca_equity"):
            fails.append(f"{intent.broker} is spot-only")
        blocked = symbol_assets(intent.symbol) & {a.upper() for a in v.asset_blocklist}
        if blocked:
            fails.append(f"{sorted(blocked)} on {intent.broker} Canada restricted list")
        if v.registration.interim_relief:
            warns.append(f"{intent.broker}: operating under interim regulatory relief ({v.registration.note or 'monitor'})")
        return fails, warns


# ---------------------------------------------------------------- synced blocklist files
class BlocklistAsset(_M):
    symbol: str
    reason: str = ""


class BlocklistFile(_M):
    venue: str
    jurisdiction: str
    source: str
    retrieved: date
    complete: bool = False
    assets: list[BlocklistAsset]


def load_blocklists(vc: "VenuesCfg", config_dir, today: date | None = None) -> tuple["VenuesCfg", list[str], list[str]]:
    """Merge each venue's asset_blocklist_file into asset_blocklist. Returns (cfg, errors, warnings).
    A missing, invalid, mismatched or stale file is an ERROR (fail closed). Offline: files only."""
    from pathlib import Path
    import yaml
    today = today or as_of_date()
    errs, warns = [], []
    venues = dict(vc.venues)
    for name, v in vc.venues.items():
        if not v.asset_blocklist_file:
            continue
        p = Path(config_dir) / v.asset_blocklist_file
        try:
            bf = BlocklistFile.model_validate(yaml.safe_load(p.read_text()))
        except FileNotFoundError:
            errs.append(f"venues: {name} blocklist file {v.asset_blocklist_file} missing"); continue
        except Exception as e:  # noqa: BLE001
            errs.append(f"venues: {name} blocklist file invalid: {e}"); continue
        if bf.venue != name:
            errs.append(f"venues: blocklist file {v.asset_blocklist_file} is for {bf.venue!r}, not {name!r}")
        age = (today - bf.retrieved).days
        if age > vc.verification_max_age_days or age < 0:
            errs.append(f"venues: {name} blocklist retrieved {bf.retrieved} is stale/invalid (> {vc.verification_max_age_days} days); re-sync")
        if not bf.complete:
            warns.append(f"venues: {name} blocklist marked incomplete; sync with the venue's published list")
        merged = sorted({a.upper() for a in v.asset_blocklist} | {a.symbol.upper() for a in bf.assets})
        venues[name] = v.model_copy(update={"asset_blocklist": merged})
    return vc.model_copy(update={"venues": venues}), errs, warns
