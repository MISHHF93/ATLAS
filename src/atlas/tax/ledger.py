"""Tax ledger wired to paper fills. Every paper fill becomes a tax Trade event
(CAD via BoC file or the fill's labelled fx rate). Optional SQLite persistence.
Record keeping only. NOT TAX ADVICE."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from atlas.tax.config import TaxCfg
from atlas.tax.engine import TaxEngine, TaxReport
from atlas.tax.entities import Affiliations, Entity
from atlas.tax.events import Trade
from atlas.tax.fx import BocFxProvider, FxQuote

from atlas.ops.timez import TORONTO as TOR  # noqa: E402
CRYPTO = {"crypto_spot", "crypto"}


def _d(x: float) -> Decimal:
    return Decimal(repr(float(x)))


class TaxLedger:
    def __init__(self, cfg: TaxCfg | None = None, fx: BocFxProvider | None = None, db_path: str = ":memory:",
                 clock=lambda: datetime.now(TOR)):
        self.cfg = cfg or TaxCfg()
        ents = [Entity(self.cfg.entity.id, self.cfg.entity.kind, self.cfg.entity.taxpayer)]
        ents += [Entity(e.id, e.kind, e.taxpayer) for e in self.cfg.other_entities]
        self.entity = self.cfg.entity.id
        self.fx = fx
        self.engine = TaxEngine(ents, Affiliations([set(g) for g in self.cfg.affiliations]), fx,
                                include_crypto_in_t1135=self.cfg.include_crypto_in_t1135)
        self.events: list = []
        self.clock = clock
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS tax_events (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        if db_path != ":memory:":
            from atlas.risk.state_store import restrict_sqlite_files
            restrict_sqlite_files(db_path)
        for (body,) in self.db.execute("SELECT body FROM tax_events ORDER BY rowid"):
            self.events.append(self._decode(json.loads(body)))

    @classmethod
    def from_config(cls, cfg: TaxCfg, config_dir: str | Path, db_path: str = ":memory:", **kw) -> "TaxLedger":
        fx = None
        if cfg.fx.source == "boc_file":
            if not cfg.fx.boc_file:
                raise ValueError("tax.yaml fx.source=boc_file needs fx.boc_file")
            fx = BocFxProvider.from_valet_json(Path(config_dir) / cfg.fx.boc_file)
        return cls(cfg, fx, db_path, **kw)

    # ---------------------------------------------------------------- fills
    def on_fill(self, f) -> Trade:
        ts = getattr(f, "ts", None) or self.clock()
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        ccy = getattr(f, "currency", "CAD") or "CAD"
        rate = _d(getattr(f, "fx_rate", 1.0) or 1.0)
        if ccy == "CAD":
            fxq = FxQuote(Decimal(1), "identity (CAD)", ts.astimezone(TOR).date())
        elif self.fx is not None:
            fxq = self.fx.quote(ccy, ts.astimezone(TOR).date())
        else:
            fxq = FxQuote(rate, f"paper fill fx_rate_to_base {ccy}CAD (NOT Bank of Canada; replace before filing)",
                          ts.astimezone(TOR).date())
        asset_class = getattr(f, "asset_class", "equity")
        prop = getattr(f, "issuer", None) or f.symbol
        fee_ccy = _d(f.commission) / rate if ccy != "CAD" else _d(f.commission)  # paper commission is in CAD base
        t = Trade(id=f.order_id, entity=self.entity, venue=getattr(f, "broker", "paper_sim"), ts=ts, property=prop,
                  side=f.side, qty=_d(f.qty), price=_d(f.price), currency=ccy, fee=fee_ccy.quantize(Decimal("0.000001")),
                  asset_type="crypto" if asset_class in CRYPTO else "security",
                  foreign=ccy in self.cfg.foreign_currencies and asset_class not in CRYPTO, automated=True, fx=fxq)
        self.add(t)
        return t

    def add(self, t: Trade) -> None:
        self.events.append(t)
        self.db.execute("INSERT OR REPLACE INTO tax_events VALUES (?,?)", (t.id, json.dumps(self._encode(t))))
        self.db.commit()

    def report(self) -> TaxReport:
        return self.engine.run(self.events)

    # ---------------------------------------------------------------- persistence
    @staticmethod
    def _encode(t: Trade) -> dict:
        d = {k: getattr(t, k) for k in ("id", "entity", "venue", "property", "side", "currency", "asset_type", "foreign", "automated")}
        d |= {"ts": t.ts.isoformat(), "qty": str(t.qty), "price": str(t.price), "fee": str(t.fee)}
        if t.fx:
            d["fx"] = {"rate": str(t.fx.rate), "source": t.fx.source, "rate_date": t.fx.rate_date.isoformat()}
        return d

    @staticmethod
    def _decode(d: dict) -> Trade:
        fx = d.pop("fx", None)
        return Trade(**{**d, "ts": datetime.fromisoformat(d["ts"]), "qty": Decimal(d["qty"]), "price": Decimal(d["price"]),
                        "fee": Decimal(d["fee"]),
                        "fx": FxQuote(Decimal(fx["rate"]), fx["source"], date.fromisoformat(fx["rate_date"])) if fx else None})
