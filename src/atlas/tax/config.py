"""tax.yaml schema. Record keeping only. NOT TAX ADVICE."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from atlas.tax.entities import Kind


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityCfg(_M):
    id: str
    kind: Kind
    taxpayer: str


class FxCfg(_M):
    source: Literal["fill", "boc_file"] = "fill"
    boc_file: str | None = None


class BocFetchCfg(_M):
    enabled: bool = False
    series: list[str] = Field(default_factory=lambda: ["FXUSDCAD"])
    cache_file: str = "../data/boc_valet_fx.json"


class TaxCfg(_M):
    version: int = 1
    entity: EntityCfg = EntityCfg(id="masharai-personal", kind="individual", taxpayer="masharai")
    other_entities: list[EntityCfg] = []
    affiliations: list[list[str]] = []
    superficial_loss_guard: Literal["warn", "block", "off"] = "warn"
    fx: FxCfg = FxCfg()
    boc_fetch: BocFetchCfg = BocFetchCfg()
    foreign_currencies: list[str] = ["USD", "EUR", "GBP"]
    include_crypto_in_t1135: bool = False
