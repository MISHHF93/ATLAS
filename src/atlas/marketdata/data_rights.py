"""Local, scope-specific evidence admission for retained market data and ML.

Public access does not establish ML rights. A trusted operator records a
reviewed agreement; this code checks scope and integrity, not legal validity.
There is deliberately no HTTP endpoint that can create these grants.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

POLICY_ENV = "ATLAS_DATA_USE_POLICY"
USES = Literal["training", "retention"]


class DataUseDenied(PermissionError):
    def __init__(self, decision: dict):
        self.decision = decision
        super().__init__(decision["reason"])


class DataUseGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grant_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    symbols: list[str] = Field(min_length=1, max_length=512)
    resolutions_seconds: list[int] = Field(min_length=1, max_length=32)
    allowed_uses: list[USES] = Field(min_length=1)
    license_ref: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    approved_at: AwareDatetime
    expires_at: AwareDatetime
    evidence_path: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    written_permission_confirmed: Literal[True]


class DataUsePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    grants: list[DataUseGrant] = Field(max_length=128)


def canonical_provider_id(provider: str) -> str:
    return {"coinbase_exchange_live_api": "coinbase_exchange_public",
            "yahoo_equities_chart_api": "yahoo_chart_public"}.get(provider, provider)


def check_data_use(provider_id: str, symbol: str, bucket_seconds: int, use: USES,
                   *, now: datetime | None = None) -> dict:
    provider = canonical_provider_id(provider_id)
    moment = now or datetime.now(timezone.utc)
    base = {"provider_id": provider, "symbol": symbol.upper(), "bucket_seconds": bucket_seconds,
            "intended_use": use, "allowed": False, "state": "unverified", "execution_permission": "none"}
    configured = os.environ.get(POLICY_ENV)
    if not configured:
        return {**base, "reason": f"{provider}: no recorded permission for {use}. Public API access is not ML or retention authorization."}
    try:
        policy_path = Path(configured)
        if policy_path.stat().st_size > 1_000_000:
            raise ValueError("Policy is too large")
        data = policy_path.read_bytes()
        policy = DataUsePolicy.model_validate_json(data)
        digest = hashlib.sha256(data).hexdigest()
        for grant in policy.grants:
            if (canonical_provider_id(grant.provider_id) != provider or use not in grant.allowed_uses
                    or symbol.upper() not in {item.upper() for item in grant.symbols}
                    or bucket_seconds not in grant.resolutions_seconds):
                continue
            if not grant.approved_at <= moment < grant.expires_at or grant.approved_at >= grant.expires_at:
                continue
            evidence = Path(grant.evidence_path)
            if not evidence.is_absolute():
                evidence = policy_path.parent / evidence
            if evidence.stat().st_size > 20_000_000:
                raise ValueError("Evidence is too large")
            if hashlib.sha256(evidence.read_bytes()).hexdigest() != grant.evidence_sha256:
                continue
            return {**base, "allowed": True, "state": "operator_attested", "grant_id": grant.grant_id,
                    "policy_sha256": digest, "license_ref": grant.license_ref,
                    "reason": "In-scope, unexpired operator-recorded written permission. This is not legal certification."}
    except (OSError, ValueError, TypeError):
        return {**base, "state": "invalid_evidence", "reason": f"{provider}: data-use evidence is missing, invalid or unreadable; {use} is blocked."}
    return {**base, "reason": f"{provider}: no in-scope, current, integrity-checked permission for {use}."}


def require_data_use(provider_id: str, symbol: str, bucket_seconds: int, use: USES) -> dict:
    decision = check_data_use(provider_id, symbol, bucket_seconds, use)
    if not decision["allowed"]:
        raise DataUseDenied(decision)
    return decision
