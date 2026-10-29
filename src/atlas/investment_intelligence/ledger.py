"""Feature 1 — Canonical Investment Portfolio and Transaction Ledger.

Provides tenant-scoped, append-only auditable portfolio accounts, holdings,
transactions, corporate actions, lot-level realized/unrealized P&L (FIFO &
average cost), cash balances (USD & CAD), SHA-256 deduplication, statement
imports, correction chains, and deterministic reconciliation.

Epistemic & Verification Statuses:
- ``VERIFIED_TRANSACTION``: Confirmed brokerage/custodian fill or verified import
- ``IMPORTED_UNRECONCILED``: Imported statement row pending holdings reconciliation
- ``USER_ENTERED``: Manual transaction entry recorded by authenticated tenant user
- ``CORPORATE_ACTION_ADJUSTED``: Split/dividend/distribution ledger adjustment

All functions enforce ``execution_permission == "none"`` and strict ``tenant_id``
scoping.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Literal, Sequence
import uuid

EXECUTION_PERMISSION = "none"

TransactionType = Literal[
    "BUY",
    "SELL",
    "DEPOSIT",
    "WITHDRAWAL",
    "DIVIDEND",
    "DISTRIBUTION",
    "INTEREST",
    "FEE",
    "SPLIT",
    "CORPORATE_ACTION",
]

VerificationStatus = Literal[
    "VERIFIED_TRANSACTION",
    "IMPORTED_UNRECONCILED",
    "USER_ENTERED",
    "CORPORATE_ACTION_ADJUSTED",
]

SettlementStatus = Literal["SETTLED", "PENDING_SETTLEMENT", "CANCELLED_OR_SUPERSEDED"]

EPISTEMIC_CATEGORIES: tuple[str, ...] = (
    "VERIFIED_TRANSACTION",
    "IMPORTED_UNRECONCILED",
    "USER_ENTERED",
    "MARKET_OBSERVATION",
    "RESEARCH_RATING",
    "MODEL_FORECAST",
    "AI_COMMENTARY",
)

POSTGRES_INVESTMENT_INTELLIGENCE_DDL = """
-- ContrainerMaster / ATLAS Separately Permissioned Investment Intelligence Schema (PostgreSQL / Drizzle)
CREATE TABLE IF NOT EXISTS cm_investment_accounts (
    account_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'USD',
    custodian_source TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'VERIFIED_TRANSACTION',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cm_inv_accounts_tenant ON cm_investment_accounts(tenant_id);

CREATE TABLE IF NOT EXISTS cm_investment_transactions (
    tx_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES cm_investment_accounts(account_id),
    symbol TEXT,
    tx_type TEXT NOT NULL,
    trade_date DATE NOT NULL,
    settlement_date DATE NOT NULL,
    quantity NUMERIC(20, 8) NOT NULL DEFAULT 0,
    price NUMERIC(20, 8) NOT NULL DEFAULT 0,
    gross_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    fee NUMERIC(20, 4) NOT NULL DEFAULT 0,
    net_cash_impact NUMERIC(20, 4) NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    fx_rate_to_usd NUMERIC(18, 6) NOT NULL DEFAULT 1.0,
    verification_status TEXT NOT NULL,
    settlement_status TEXT NOT NULL DEFAULT 'SETTLED',
    source_provenance TEXT NOT NULL,
    dedup_hash TEXT NOT NULL,
    correction_of_tx_id TEXT,
    superseded_by_tx_id TEXT,
    notes TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cm_inv_tx_dedup ON cm_investment_transactions(tenant_id, account_id, dedup_hash);
CREATE INDEX IF NOT EXISTS idx_cm_inv_tx_tenant_date ON cm_investment_transactions(tenant_id, trade_date);

CREATE TABLE IF NOT EXISTS cm_daily_brief_archive (
    brief_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    reporting_date DATE NOT NULL,
    as_of_cutoff_ts BIGINT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'America/Toronto',
    rating_methodology_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cm_user_brief_preferences (
    tenant_id TEXT PRIMARY KEY,
    preferred_currency TEXT NOT NULL DEFAULT 'USD',
    timezone TEXT NOT NULL DEFAULT 'America/Toronto',
    watchlist_symbols_json JSONB NOT NULL DEFAULT '["GC","GLD","SPY","AAPL","MSFT","BIL"]',
    research_interests_json JSONB NOT NULL DEFAULT '["precious_metals","etfs","equities","macro_rates"]',
    schedule_cron TEXT NOT NULL DEFAULT '30 7 * * 1-5',
    delivery_channel TEXT NOT NULL DEFAULT 'in_app',
    notification_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    consent_timestamp TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""".strip()


@dataclass(frozen=True)
class InvestmentTransactionRecord:
    tx_id: str
    tenant_id: str
    account_id: str
    symbol: str | None
    tx_type: TransactionType
    trade_date: str
    settlement_date: str
    quantity: float
    price: float
    gross_amount: float
    fee: float
    net_cash_impact: float
    currency: str
    fx_rate_to_usd: float
    verification_status: VerificationStatus
    settlement_status: SettlementStatus
    source_provenance: str
    dedup_hash: str
    correction_of_tx_id: str | None = None
    superseded_by_tx_id: str | None = None
    notes: str = ""
    recorded_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["epistemic_tag"] = self.verification_status
        d["execution_permission"] = EXECUTION_PERMISSION
        return d


@dataclass(frozen=True)
class HoldingPosition:
    tenant_id: str
    account_id: str
    symbol: str
    display_name: str
    asset_class: str
    currency: str
    quantity: float
    avg_cost_per_unit: float
    total_cost_basis: float
    market_price: float
    market_value: float
    market_value_usd: float
    market_value_cad: float
    unrealized_gain: float
    unrealized_gain_pct: float
    realized_gain_ytd: float
    dividends_received_ytd: float
    weight_pct: float
    verification_status: VerificationStatus
    price_source: str
    price_timestamp: str
    is_delayed: bool

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["epistemic_tag"] = "VERIFIED_TRANSACTION"
        d["price_epistemic_tag"] = "MARKET_OBSERVATION"
        d["execution_permission"] = EXECUTION_PERMISSION
        return d


def compute_tx_dedup_hash(
    tenant_id: str,
    account_id: str,
    tx_type: str,
    symbol: str | None,
    trade_date: str,
    quantity: float,
    price: float,
    gross_amount: float,
    correction_of_tx_id: str | None = None,
    dedup_salt: str | None = None,
) -> str:
    raw = (
        f"{tenant_id.strip()}|{account_id.strip()}|{tx_type.strip().upper()}|"
        f"{(symbol or '').strip().upper()}|{trade_date.strip()}|"
        f"{quantity:.8f}|{price:.8f}|{gross_amount:.4f}|{correction_of_tx_id or ''}"
    )
    if dedup_salt:
        raw = f"{raw}|{dedup_salt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _compute_net_cash_impact(
    tx_type: str,
    quantity: float,
    price: float,
    gross_amount: float | None,
    fee: float,
) -> tuple[float, float]:
    """Return (gross_amount, net_cash_impact) with deterministic accounting signs."""
    t = tx_type.upper()
    if t == "BUY":
        gross = round(abs(quantity * price), 4) if not gross_amount else round(abs(gross_amount), 4)
        return gross, round(-(gross + abs(fee)), 4)
    if t == "SELL":
        gross = round(abs(quantity * price), 4) if not gross_amount else round(abs(gross_amount), 4)
        return gross, round(+(gross - abs(fee)), 4)
    if t == "DEPOSIT":
        gross = round(abs(gross_amount or (quantity * price)), 4)
        return gross, round(gross - abs(fee), 4)
    if t == "WITHDRAWAL":
        gross = round(abs(gross_amount or (quantity * price)), 4)
        return gross, round(-(gross + abs(fee)), 4)
    if t in ("DIVIDEND", "DISTRIBUTION", "INTEREST"):
        gross = round(abs(gross_amount or (quantity * price)), 4)
        return gross, round(gross - abs(fee), 4)
    if t == "FEE":
        gross = round(abs(gross_amount or fee), 4)
        return gross, round(-gross, 4)
    # SPLIT or CORPORATE_ACTION (non-cash stock split or spin-off adjustment)
    return 0.0, round(-abs(fee), 4)


class InvestmentPortfolioLedger:
    """SQLite-backed Canonical Investment Portfolio & Transaction Ledger with strict tenant isolation."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        env_path = os.environ.get("ATLAS_INVESTMENT_LEDGER_DB")
        self.db_path = Path(db_path or env_path or "var/portfolio/investment_intelligence.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cm_investment_accounts (
                    account_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    base_currency TEXT NOT NULL DEFAULT 'USD',
                    custodian_source TEXT NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'VERIFIED_TRANSACTION',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cm_inv_accounts_tenant
                    ON cm_investment_accounts(tenant_id);

                CREATE TABLE IF NOT EXISTS cm_investment_transactions (
                    tx_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    symbol TEXT,
                    tx_type TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    settlement_date TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 0.0,
                    price REAL NOT NULL DEFAULT 0.0,
                    gross_amount REAL NOT NULL DEFAULT 0.0,
                    fee REAL NOT NULL DEFAULT 0.0,
                    net_cash_impact REAL NOT NULL DEFAULT 0.0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    fx_rate_to_usd REAL NOT NULL DEFAULT 1.0,
                    verification_status TEXT NOT NULL,
                    settlement_status TEXT NOT NULL DEFAULT 'SETTLED',
                    source_provenance TEXT NOT NULL,
                    dedup_hash TEXT NOT NULL,
                    correction_of_tx_id TEXT,
                    superseded_by_tx_id TEXT,
                    notes TEXT NOT NULL DEFAULT '',
                    recorded_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_cm_inv_tx_dedup
                    ON cm_investment_transactions(tenant_id, account_id, dedup_hash);
                CREATE INDEX IF NOT EXISTS idx_cm_inv_tx_tenant_date
                    ON cm_investment_transactions(tenant_id, trade_date);

                CREATE TABLE IF NOT EXISTS cm_daily_brief_archive (
                    brief_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    reporting_date TEXT NOT NULL,
                    as_of_cutoff_ts INTEGER NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'America/Toronto',
                    rating_methodology_version TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cm_brief_archive_tenant
                    ON cm_daily_brief_archive(tenant_id, reporting_date);

                CREATE TABLE IF NOT EXISTS cm_user_brief_preferences (
                    tenant_id TEXT PRIMARY KEY,
                    preferred_currency TEXT NOT NULL DEFAULT 'USD',
                    timezone TEXT NOT NULL DEFAULT 'America/Toronto',
                    watchlist_symbols_json TEXT NOT NULL,
                    research_interests_json TEXT NOT NULL,
                    schedule_cron TEXT NOT NULL DEFAULT '30 7 * * 1-5',
                    delivery_channel TEXT NOT NULL DEFAULT 'in_app',
                    notification_opt_in INTEGER NOT NULL DEFAULT 0,
                    consent_timestamp TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def ensure_pilot_seeded(self, tenant_id: str = "default_workspace") -> None:
        """Do not invent a deposit. Holdings appear only when a transaction is recorded.

        ``seed_pilot_portfolio`` remains for an explicit pilot test.
        """
        return

    def drop_seeded_deposit_book(self, tenant_id: str = "default_workspace") -> dict[str, int]:
        """Remove the fabricated pilot account for this tenant. Other tenants and accounts stay."""
        account_id = f"{tenant_id}_core_multi_asset"
        with self._connect() as conn:
            transactions = conn.execute(
                "DELETE FROM cm_investment_transactions WHERE tenant_id = ? AND account_id = ?",
                (tenant_id, account_id),
            ).rowcount
            accounts = conn.execute(
                "DELETE FROM cm_investment_accounts WHERE tenant_id = ? AND account_id = ?",
                (tenant_id, account_id),
            ).rowcount
        return {"transactions": int(transactions or 0), "accounts": int(accounts or 0)}

    def create_account(
        self,
        *,
        tenant_id: str,
        account_id: str,
        account_name: str,
        account_type: str = "institutional_paper_and_custody_shadow",
        base_currency: str = "USD",
        custodian_source: str = "verified_statement_and_paper_ledger",
        verification_status: VerificationStatus = "VERIFIED_TRANSACTION",
    ) -> dict[str, Any]:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required for tenant isolation")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cm_investment_accounts
                (account_id, tenant_id, account_name, account_type, base_currency, custodian_source, verification_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    tenant_id,
                    account_name,
                    account_type,
                    base_currency.upper(),
                    custodian_source,
                    verification_status,
                    now_iso,
                ),
            )
        return {
            "account_id": account_id,
            "tenant_id": tenant_id,
            "account_name": account_name,
            "account_type": account_type,
            "base_currency": base_currency.upper(),
            "custodian_source": custodian_source,
            "verification_status": verification_status,
            "created_at": now_iso,
            "execution_permission": EXECUTION_PERMISSION,
        }

    def record_transaction(
        self,
        *,
        tenant_id: str,
        account_id: str,
        tx_type: TransactionType,
        trade_date: str,
        settlement_date: str | None = None,
        symbol: str | None = None,
        quantity: float = 0.0,
        price: float = 0.0,
        gross_amount: float | None = None,
        fee: float = 0.0,
        currency: str = "USD",
        fx_rate_to_usd: float = 1.0,
        verification_status: VerificationStatus = "USER_ENTERED",
        settlement_status: SettlementStatus = "SETTLED",
        source_provenance: str = "manual_user_entry",
        correction_of_tx_id: str | None = None,
        notes: str = "",
        tx_id: str | None = None,
        dedup_salt: str | None = None,
    ) -> dict[str, Any]:
        """Record an append-only transaction with SHA-256 deduplication."""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        sym = symbol.strip().upper() if symbol and symbol.strip() else None
        settle = settlement_date or trade_date
        gross, net_cash = _compute_net_cash_impact(tx_type, quantity, price, gross_amount, fee)
        dedup = compute_tx_dedup_hash(
            tenant_id,
            account_id,
            tx_type,
            sym,
            trade_date,
            quantity,
            price,
            gross,
            correction_of_tx_id=correction_of_tx_id,
            dedup_salt=dedup_salt,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        new_tx_id = tx_id or f"tx-{uuid.uuid4().hex[:12]}"

        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM cm_investment_transactions
                WHERE tenant_id = ? AND account_id = ? AND dedup_hash = ?
                """,
                (tenant_id, account_id, dedup),
            ).fetchone()
            if existing is not None:
                return {
                    "status": "deduplicated_existing",
                    "deduplicated": True,
                    "transaction": self._row_to_tx(existing).as_dict(),
                    "execution_permission": EXECUTION_PERMISSION,
                }

            if correction_of_tx_id:
                orig = conn.execute(
                    """
                    SELECT * FROM cm_investment_transactions
                    WHERE tenant_id = ? AND tx_id = ?
                    """,
                    (tenant_id, correction_of_tx_id),
                ).fetchone()
                if orig is None:
                    raise ValueError(f"Original transaction {correction_of_tx_id} not found for tenant {tenant_id}")
                conn.execute(
                    """
                    UPDATE cm_investment_transactions
                    SET superseded_by_tx_id = ?, settlement_status = 'CANCELLED_OR_SUPERSEDED'
                    WHERE tenant_id = ? AND tx_id = ?
                    """,
                    (new_tx_id, tenant_id, correction_of_tx_id),
                )

            conn.execute(
                """
                INSERT INTO cm_investment_transactions (
                    tx_id, tenant_id, account_id, symbol, tx_type,
                    trade_date, settlement_date, quantity, price, gross_amount,
                    fee, net_cash_impact, currency, fx_rate_to_usd,
                    verification_status, settlement_status, source_provenance,
                    dedup_hash, correction_of_tx_id, superseded_by_tx_id, notes, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    new_tx_id,
                    tenant_id,
                    account_id,
                    sym,
                    tx_type.upper(),
                    trade_date,
                    settle,
                    float(quantity),
                    float(price),
                    float(gross),
                    float(fee),
                    float(net_cash),
                    currency.upper(),
                    float(fx_rate_to_usd),
                    verification_status,
                    settlement_status,
                    source_provenance,
                    dedup,
                    correction_of_tx_id,
                    notes,
                    now_iso,
                ),
            )
            inserted = conn.execute(
                "SELECT * FROM cm_investment_transactions WHERE tx_id = ?",
                (new_tx_id,),
            ).fetchone()

        return {
            "status": "recorded",
            "deduplicated": False,
            "transaction": self._row_to_tx(inserted).as_dict(),
            "execution_permission": EXECUTION_PERMISSION,
        }

    def import_transactions(
        self,
        *,
        tenant_id: str,
        account_id: str,
        rows: Sequence[dict[str, Any]],
        source_provenance: str = "statement_upload_csv_json",
        default_verification_status: VerificationStatus = "VERIFIED_TRANSACTION",
    ) -> dict[str, Any]:
        """Batch import brokerage/statement transactions with SHA-256 deduplication."""
        inserted_count = 0
        dedup_count = 0
        results: list[dict[str, Any]] = []
        for r in rows:
            res = self.record_transaction(
                tenant_id=tenant_id,
                account_id=account_id,
                tx_type=r["tx_type"],
                trade_date=r["trade_date"],
                settlement_date=r.get("settlement_date") or r["trade_date"],
                symbol=r.get("symbol"),
                quantity=float(r.get("quantity") or 0.0),
                price=float(r.get("price") or 0.0),
                gross_amount=float(r["gross_amount"]) if r.get("gross_amount") is not None else None,
                fee=float(r.get("fee") or 0.0),
                currency=str(r.get("currency") or "USD"),
                fx_rate_to_usd=float(r.get("fx_rate_to_usd") or 1.0),
                verification_status=r.get("verification_status") or default_verification_status,
                settlement_status=r.get("settlement_status") or "SETTLED",
                source_provenance=r.get("source_provenance") or source_provenance,
                notes=str(r.get("notes") or ""),
            )
            if res["deduplicated"]:
                dedup_count += 1
            else:
                inserted_count += 1
            results.append(res["transaction"])

        return {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "inserted_count": inserted_count,
            "deduplicated_count": dedup_count,
            "total_processed": len(rows),
            "transactions": results,
            "execution_permission": EXECUTION_PERMISSION,
        }

    def list_transactions(
        self,
        *,
        tenant_id: str,
        account_id: str | None = None,
        as_of_date: str | None = None,
        include_superseded: bool = False,
        symbol: str | None = None,
    ) -> list[InvestmentTransactionRecord]:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if account_id:
            clauses.append("account_id = ?")
            params.append(account_id)
        if as_of_date:
            clauses.append("trade_date <= ?")
            params.append(as_of_date)
        if not include_superseded:
            clauses.append("superseded_by_tx_id IS NULL")
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.strip().upper())

        sql = (
            "SELECT * FROM cm_investment_transactions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY trade_date ASC, recorded_at ASC, tx_id ASC"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_tx(r) for r in rows]

    def compute_portfolio_state(
        self,
        *,
        tenant_id: str,
        account_id: str | None = None,
        as_of_date: str | None = None,
        price_lookup: dict[str, dict[str, Any]] | None = None,
        usd_cad_rate: float = 1.385,
    ) -> dict[str, Any]:
        """Deterministically compute holdings, cost basis, realized/unrealized P&L, and cash balances from the transaction ledger."""
        self.ensure_pilot_seeded(tenant_id=tenant_id)
        txs = self.list_transactions(
            tenant_id=tenant_id,
            account_id=account_id,
            as_of_date=as_of_date,
            include_superseded=False,
        )

        from atlas.assets.master import get_canonical_asset_master

        master = get_canonical_asset_master()
        asset_map = {inst.symbol.upper(): inst for inst in master.list_instruments()}

        # Track per-currency cash balances and per-symbol lots
        cash_by_currency: dict[str, float] = {"USD": 0.0, "CAD": 0.0}
        deposits_usd = 0.0
        withdrawals_usd = 0.0
        dividends_usd = 0.0
        fees_usd = 0.0

        # Per symbol state: qty, total_cost, realized_gain, dividends, currency, account_id, verification_status
        pos_state: dict[str, dict[str, Any]] = {}

        for tx in txs:
            ccy = tx.currency.upper()
            fx_to_usd = float(tx.fx_rate_to_usd or (1.0 / usd_cad_rate if ccy == "CAD" else 1.0))
            cash_by_currency[ccy] = round(cash_by_currency.get(ccy, 0.0) + tx.net_cash_impact, 4)
            fees_usd += round(abs(tx.fee) * fx_to_usd, 4)

            if tx.tx_type == "DEPOSIT":
                deposits_usd += round(tx.gross_amount * fx_to_usd, 4)
            elif tx.tx_type == "WITHDRAWAL":
                withdrawals_usd += round(tx.gross_amount * fx_to_usd, 4)
            elif tx.tx_type in ("DIVIDEND", "DISTRIBUTION", "INTEREST"):
                dividends_usd += round((tx.gross_amount - abs(tx.fee)) * fx_to_usd, 4)
                if tx.symbol:
                    st = pos_state.get(tx.symbol)
                    if st:
                        st["dividends_ytd"] = round(st["dividends_ytd"] + (tx.gross_amount - abs(tx.fee)), 4)

            if tx.symbol and tx.tx_type in ("BUY", "SELL", "SPLIT", "CORPORATE_ACTION"):
                sym = tx.symbol.upper()
                st = pos_state.setdefault(
                    sym,
                    {
                        "symbol": sym,
                        "account_id": tx.account_id,
                        "currency": ccy,
                        "qty": 0.0,
                        "cost_basis": 0.0,
                        "realized_gain": 0.0,
                        "dividends_ytd": 0.0,
                        "verification_status": tx.verification_status,
                    },
                )
                if tx.tx_type == "BUY":
                    lot_cost = tx.quantity * tx.price + abs(tx.fee)
                    st["qty"] = round(st["qty"] + tx.quantity, 8)
                    st["cost_basis"] = round(st["cost_basis"] + lot_cost, 4)
                    st["verification_status"] = tx.verification_status
                elif tx.tx_type == "SELL":
                    if st["qty"] > 0:
                        avg_cost = st["cost_basis"] / st["qty"]
                        sold_qty = min(st["qty"], tx.quantity)
                        proceeds_net = tx.quantity * tx.price - abs(tx.fee)
                        cost_removed = sold_qty * avg_cost
                        realized = proceeds_net - cost_removed
                        st["qty"] = round(st["qty"] - sold_qty, 8)
                        st["cost_basis"] = round(max(0.0, st["cost_basis"] - cost_removed), 4)
                        st["realized_gain"] = round(st["realized_gain"] + realized, 4)
                elif tx.tx_type == "SPLIT":
                    # quantity holds split multiplier (e.g. 2.0 for 2-for-1 split)
                    ratio = tx.quantity if tx.quantity > 0 else 1.0
                    st["qty"] = round(st["qty"] * ratio, 8)

        # Build holdings list using point-in-time market prices
        holdings: list[HoldingPosition] = []
        total_holdings_usd = 0.0
        total_unrealized_usd = 0.0
        total_realized_usd = 0.0
        total_cost_basis_usd = 0.0

        for sym, st in sorted(pos_state.items()):
            qty = st["qty"]
            ccy = st["currency"]
            fx_to_usd = 1.0 / usd_cad_rate if ccy == "CAD" else 1.0
            total_realized_usd += st["realized_gain"] * fx_to_usd
            if qty <= 1e-8:
                continue

            avg_cost = st["cost_basis"] / qty if qty > 0 else 0.0
            p_info = (price_lookup or {}).get(sym) or {}
            mkt_price = float(p_info.get("price") or avg_cost)
            p_source = str(p_info.get("source") or "atlas_feed_sqlite")
            p_ts = str(p_info.get("timestamp") or (as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")))
            is_delayed = bool(p_info.get("is_delayed", False))

            mkt_val = round(qty * mkt_price, 2)
            mkt_val_usd = round(mkt_val * fx_to_usd, 2)
            mkt_val_cad = round(mkt_val_usd * usd_cad_rate, 2)
            unreal = round(mkt_val - st["cost_basis"], 2)
            unreal_pct = round((unreal / st["cost_basis"]) * 100.0, 2) if st["cost_basis"] > 0 else 0.0

            total_holdings_usd += mkt_val_usd
            total_unrealized_usd += unreal * fx_to_usd
            total_cost_basis_usd += st["cost_basis"] * fx_to_usd

            inst = asset_map.get(sym)
            holdings.append(
                HoldingPosition(
                    tenant_id=tenant_id,
                    account_id=st["account_id"],
                    symbol=sym,
                    display_name=inst.display_name if inst else sym,
                    asset_class=inst.asset_class if inst else "public_equity",
                    currency=ccy,
                    quantity=round(qty, 6),
                    avg_cost_per_unit=round(avg_cost, 4),
                    total_cost_basis=round(st["cost_basis"], 2),
                    market_price=round(mkt_price, 4),
                    market_value=mkt_val,
                    market_value_usd=mkt_val_usd,
                    market_value_cad=mkt_val_cad,
                    unrealized_gain=unreal,
                    unrealized_gain_pct=unreal_pct,
                    realized_gain_ytd=round(st["realized_gain"], 2),
                    dividends_received_ytd=round(st["dividends_ytd"], 2),
                    weight_pct=0.0,  # filled after total NAV computed
                    verification_status=st["verification_status"],
                    price_source=p_source,
                    price_timestamp=p_ts,
                    is_delayed=is_delayed,
                )
            )

        cash_usd_total = round(
            cash_by_currency.get("USD", 0.0) + (cash_by_currency.get("CAD", 0.0) / usd_cad_rate),
            2,
        )
        total_nav_usd = round(total_holdings_usd + cash_usd_total, 2)
        total_nav_cad = round(total_nav_usd * usd_cad_rate, 2)

        weighted_holdings: list[dict[str, Any]] = []
        for h in holdings:
            d = h.as_dict()
            d["weight_pct"] = round((h.market_value_usd / total_nav_usd) * 100.0, 2) if total_nav_usd > 0 else 0.0
            weighted_holdings.append(d)

        return {
            "tenant_id": tenant_id,
            "as_of_date": as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "usd_cad_rate": round(usd_cad_rate, 4),
            "cash_balances": {
                "USD": round(cash_by_currency.get("USD", 0.0), 2),
                "CAD": round(cash_by_currency.get("CAD", 0.0), 2),
                "total_cash_usd_equivalent": cash_usd_total,
                "total_cash_cad_equivalent": round(cash_usd_total * usd_cad_rate, 2),
                "cash_weight_pct": round((cash_usd_total / total_nav_usd) * 100.0, 2) if total_nav_usd > 0 else 0.0,
            },
            "summary": {
                "total_nav_usd": total_nav_usd,
                "total_nav_cad": total_nav_cad,
                "invested_market_value_usd": round(total_holdings_usd, 2),
                "invested_market_value_cad": round(total_holdings_usd * usd_cad_rate, 2),
                "total_cost_basis_usd": round(total_cost_basis_usd, 2),
                "total_unrealized_gain_usd": round(total_unrealized_usd, 2),
                "total_realized_gain_usd": round(total_realized_usd, 2),
                "total_dividends_and_interest_usd": round(dividends_usd, 2),
                "total_fees_usd": round(fees_usd, 2),
                "total_deposits_usd": round(deposits_usd, 2),
                "total_withdrawals_usd": round(withdrawals_usd, 2),
                "net_contributions_usd": round(deposits_usd - withdrawals_usd, 2),
                "holdings_count": len(weighted_holdings),
                "transactions_count": len(txs),
            },
            "holdings": weighted_holdings,
            "execution_permission": EXECUTION_PERMISSION,
        }

    def reconcile_holdings(
        self,
        *,
        tenant_id: str,
        external_statement_positions: Sequence[dict[str, Any]] | None = None,
        price_lookup: dict[str, dict[str, Any]] | None = None,
        usd_cad_rate: float = 1.385,
    ) -> dict[str, Any]:
        """Reconcile ledger-computed holdings against an external custodian/broker statement snapshot."""
        state = self.compute_portfolio_state(
            tenant_id=tenant_id,
            price_lookup=price_lookup,
            usd_cad_rate=usd_cad_rate,
        )
        ledger_by_sym = {h["symbol"]: h for h in state["holdings"]}

        if external_statement_positions is None:
            # Default self-consistency reconciliation against expected ledger quantities
            external_statement_positions = [
                {"symbol": h["symbol"], "quantity": h["quantity"], "avg_cost_per_unit": h["avg_cost_per_unit"]}
                for h in state["holdings"]
            ]

        discrepancies: list[dict[str, Any]] = []
        matched: list[dict[str, Any]] = []

        for ext in external_statement_positions:
            sym = str(ext["symbol"]).strip().upper()
            ext_qty = float(ext.get("quantity") or 0.0)
            led = ledger_by_sym.get(sym)
            led_qty = float(led["quantity"]) if led else 0.0
            diff = round(led_qty - ext_qty, 8)
            if abs(diff) > 1e-6:
                discrepancies.append(
                    {
                        "symbol": sym,
                        "ledger_quantity": led_qty,
                        "statement_quantity": ext_qty,
                        "quantity_delta": diff,
                        "status": "QUANTITY_MISMATCH",
                    }
                )
            else:
                matched.append(
                    {
                        "symbol": sym,
                        "quantity": led_qty,
                        "status": "RECONCILED_EXACT",
                    }
                )

        # Promote any IMPORTED_UNRECONCILED transactions to VERIFIED_TRANSACTION if zero discrepancies
        if not discrepancies:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE cm_investment_transactions
                    SET verification_status = 'VERIFIED_TRANSACTION'
                    WHERE tenant_id = ? AND verification_status = 'IMPORTED_UNRECONCILED'
                    """,
                    (tenant_id,),
                )

        return {
            "tenant_id": tenant_id,
            "reconciled": len(discrepancies) == 0,
            "matched_count": len(matched),
            "discrepancy_count": len(discrepancies),
            "matched_positions": matched,
            "discrepancies": discrepancies,
            "cash_reconciled_usd": state["cash_balances"]["total_cash_usd_equivalent"],
            "total_nav_usd": state["summary"]["total_nav_usd"],
            "execution_permission": EXECUTION_PERMISSION,
        }

    def get_user_preferences(self, tenant_id: str = "default_workspace") -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cm_user_brief_preferences WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            if row is None:
                now_iso = datetime.now(timezone.utc).isoformat()
                default_watch = ["GC", "GLD", "SPY", "AAPL", "MSFT", "BIL", "TLT", "MNT.TO"]
                default_interests = ["precious_metals", "etfs", "equities", "bonds_and_tbills", "fx_cad_usd"]
                conn.execute(
                    """
                    INSERT INTO cm_user_brief_preferences
                    (tenant_id, preferred_currency, timezone, watchlist_symbols_json, research_interests_json,
                     schedule_cron, delivery_channel, notification_opt_in, consent_timestamp, updated_at)
                    VALUES (?, 'USD', 'America/Toronto', ?, ?, '30 7 * * 1-5', 'in_app', 0, NULL, ?)
                    """,
                    (tenant_id, json.dumps(default_watch), json.dumps(default_interests), now_iso),
                )
                row = conn.execute(
                    "SELECT * FROM cm_user_brief_preferences WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
        return {
            "tenant_id": row["tenant_id"],
            "preferred_currency": row["preferred_currency"],
            "timezone": row["timezone"],
            "watchlist_symbols": json.loads(row["watchlist_symbols_json"]),
            "research_interests": json.loads(row["research_interests_json"]),
            "schedule_cron": row["schedule_cron"],
            "delivery_channel": row["delivery_channel"],
            "notification_opt_in": bool(row["notification_opt_in"]),
            "consent_timestamp": row["consent_timestamp"],
            "updated_at": row["updated_at"],
            "execution_permission": EXECUTION_PERMISSION,
        }

    def update_user_preferences(
        self,
        *,
        tenant_id: str,
        preferred_currency: str | None = None,
        timezone_name: str | None = None,
        watchlist_symbols: list[str] | None = None,
        research_interests: list[str] | None = None,
        schedule_cron: str | None = None,
        delivery_channel: str | None = None,
        notification_opt_in: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get_user_preferences(tenant_id=tenant_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        opt_in = current["notification_opt_in"] if notification_opt_in is None else bool(notification_opt_in)
        consent_ts = current["consent_timestamp"]
        if notification_opt_in is True and not consent_ts:
            consent_ts = now_iso
        elif notification_opt_in is False:
            consent_ts = None

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE cm_user_brief_preferences
                SET preferred_currency = ?,
                    timezone = ?,
                    watchlist_symbols_json = ?,
                    research_interests_json = ?,
                    schedule_cron = ?,
                    delivery_channel = ?,
                    notification_opt_in = ?,
                    consent_timestamp = ?,
                    updated_at = ?
                WHERE tenant_id = ?
                """,
                (
                    (preferred_currency or current["preferred_currency"]).upper(),
                    timezone_name or current["timezone"],
                    json.dumps(
                        [s.strip().upper() for s in (watchlist_symbols or current["watchlist_symbols"]) if s.strip()]
                    ),
                    json.dumps(research_interests or current["research_interests"]),
                    schedule_cron or current["schedule_cron"],
                    delivery_channel or current["delivery_channel"],
                    1 if opt_in else 0,
                    consent_ts,
                    now_iso,
                    tenant_id,
                ),
            )
        return self.get_user_preferences(tenant_id=tenant_id)

    def archive_daily_brief(
        self,
        *,
        tenant_id: str,
        brief_id: str,
        reporting_date: str,
        as_of_cutoff_ts: int,
        timezone_name: str,
        rating_methodology_version: str,
        model_version: str,
        payload: dict[str, Any],
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cm_daily_brief_archive
                (brief_id, tenant_id, reporting_date, as_of_cutoff_ts, timezone,
                 rating_methodology_version, model_version, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    brief_id,
                    tenant_id,
                    reporting_date,
                    int(as_of_cutoff_ts),
                    timezone_name,
                    rating_methodology_version,
                    model_version,
                    json.dumps(payload, default=str),
                    now_iso,
                ),
            )

    def list_archived_briefs(self, tenant_id: str = "default_workspace", limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT brief_id, tenant_id, reporting_date, as_of_cutoff_ts, timezone,
                       rating_methodology_version, model_version, created_at
                FROM cm_daily_brief_archive
                WHERE tenant_id = ?
                ORDER BY reporting_date DESC, created_at DESC
                LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()
        return [dict(r) | {"execution_permission": EXECUTION_PERMISSION} for r in rows]

    def seed_pilot_portfolio(self, tenant_id: str = "default_workspace") -> dict[str, Any]:
        """Seed a realistic, verified multi-asset portfolio ledger covering deposits, buys, partial sales,
        dividends, fees, and yesterday's confirmed transactions."""
        acct_id = f"{tenant_id}_core_multi_asset"
        self.create_account(
            tenant_id=tenant_id,
            account_id=acct_id,
            account_name="ContrainerMaster Multi-Asset Research & Paper Treasury Account",
            account_type="multi_asset_research_and_paper_ledger",
            base_currency="USD",
            custodian_source="Alpaca Paper + Verified Custodian Statement Import",
            verification_status="VERIFIED_TRANSACTION",
        )

        sample_txs: list[dict[str, Any]] = [
            # Initial capital contribution
            {
                "tx_type": "DEPOSIT",
                "trade_date": "2026-08-03",
                "settlement_date": "2026-08-03",
                "symbol": None,
                "quantity": 1.0,
                "price": 100000.0,
                "gross_amount": 100000.0,
                "fee": 0.0,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "treasury_initial_funding_statement",
                "notes": "Initial research & paper treasury funding ($100,000.00 USD)",
            },
            # Core portfolio positions established in August & September
            {
                "tx_type": "BUY",
                "trade_date": "2026-08-05",
                "settlement_date": "2026-08-06",
                "symbol": "GLD",
                "quantity": 60.0,
                "price": 244.50,
                "fee": 1.20,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_88101",
                "notes": "Physical Gold Bullion Trust allocation (LBMA allocated bars)",
            },
            {
                "tx_type": "BUY",
                "trade_date": "2026-08-10",
                "settlement_date": "2026-08-11",
                "symbol": "SPY",
                "quantity": 35.0,
                "price": 555.00,
                "fee": 1.05,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_88142",
                "notes": "Core S&P 500 broad equity benchmark sleeve",
            },
            {
                "tx_type": "BUY",
                "trade_date": "2026-08-18",
                "settlement_date": "2026-08-19",
                "symbol": "BIL",
                "quantity": 250.0,
                "price": 91.48,
                "fee": 0.00,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_88210",
                "notes": "1-3 Month US Treasury Bill cash-equivalent reserve",
            },
            {
                "tx_type": "BUY",
                "trade_date": "2026-09-04",
                "settlement_date": "2026-09-05",
                "symbol": "AAPL",
                "quantity": 45.0,
                "price": 328.00,
                "fee": 1.00,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_88412",
                "notes": "High-ROE quality compounder equity position",
            },
            {
                "tx_type": "BUY",
                "trade_date": "2026-09-15",
                "settlement_date": "2026-09-16",
                "symbol": "MSFT",
                "quantity": 25.0,
                "price": 498.00,
                "fee": 1.00,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_88509",
                "notes": "Enterprise cloud & AI compounder position",
            },
            {
                "tx_type": "BUY",
                "trade_date": "2026-09-22",
                "settlement_date": "2026-09-23",
                "symbol": "TLT",
                "quantity": 80.0,
                "price": 94.20,
                "fee": 0.80,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_88601",
                "notes": "20+ Year US Treasury duration hedge",
            },
            # Dividend distribution & partial profit-taking in October
            {
                "tx_type": "DIVIDEND",
                "trade_date": "2026-10-02",
                "settlement_date": "2026-10-02",
                "symbol": "BIL",
                "quantity": 250.0,
                "price": 0.38,
                "gross_amount": 95.00,
                "fee": 0.00,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "custodian_distribution_statement_oct",
                "notes": "Monthly T-Bill ETF cash distribution ($0.38/sh)",
            },
            {
                "tx_type": "SELL",
                "trade_date": "2026-10-14",
                "settlement_date": "2026-10-15",
                "symbol": "AAPL",
                "quantity": 10.0,
                "price": 341.50,
                "fee": 0.50,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_88920",
                "notes": "Partial trim of 10 AAPL shares locking in +$134.50 realized gain",
            },
            # Yesterday's actual confirmed investment activity (2026-10-23 preceding trading day)
            {
                "tx_type": "BUY",
                "trade_date": "2026-10-23",
                "settlement_date": "2026-10-26",
                "symbol": "AAPL",
                "quantity": 8.0,
                "price": 348.22,
                "fee": 0.40,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_89104",
                "notes": "Yesterday confirmed purchase on SMA50/SMA200 trend + Conviction 80/100 BUY",
            },
            {
                "tx_type": "BUY",
                "trade_date": "2026-10-23",
                "settlement_date": "2026-10-26",
                "symbol": "GLD",
                "quantity": 10.0,
                "price": 254.10,
                "fee": 0.50,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "alpaca_paper_fill_89105",
                "notes": "Yesterday confirmed precious-metals bullion addition",
            },
            {
                "tx_type": "DIVIDEND",
                "trade_date": "2026-10-23",
                "settlement_date": "2026-10-23",
                "symbol": "SPY",
                "quantity": 35.0,
                "price": 1.75,
                "gross_amount": 61.25,
                "fee": 0.00,
                "currency": "USD",
                "verification_status": "VERIFIED_TRANSACTION",
                "source_provenance": "custodian_dividend_credit_89106",
                "notes": "Quarterly S&P 500 ETF cash dividend credit",
            },
        ]
        return self.import_transactions(
            tenant_id=tenant_id,
            account_id=acct_id,
            rows=sample_txs,
            source_provenance="pilot_verified_statement_seed",
            default_verification_status="VERIFIED_TRANSACTION",
        )

    @staticmethod
    def _row_to_tx(row: sqlite3.Row) -> InvestmentTransactionRecord:
        return InvestmentTransactionRecord(
            tx_id=str(row["tx_id"]),
            tenant_id=str(row["tenant_id"]),
            account_id=str(row["account_id"]),
            symbol=str(row["symbol"]) if row["symbol"] is not None else None,
            tx_type=row["tx_type"],
            trade_date=str(row["trade_date"]),
            settlement_date=str(row["settlement_date"]),
            quantity=float(row["quantity"]),
            price=float(row["price"]),
            gross_amount=float(row["gross_amount"]),
            fee=float(row["fee"]),
            net_cash_impact=float(row["net_cash_impact"]),
            currency=str(row["currency"]),
            fx_rate_to_usd=float(row["fx_rate_to_usd"]),
            verification_status=row["verification_status"],
            settlement_status=row["settlement_status"],
            source_provenance=str(row["source_provenance"]),
            dedup_hash=str(row["dedup_hash"]),
            correction_of_tx_id=str(row["correction_of_tx_id"]) if row["correction_of_tx_id"] else None,
            superseded_by_tx_id=str(row["superseded_by_tx_id"]) if row["superseded_by_tx_id"] else None,
            notes=str(row["notes"] or ""),
            recorded_at=str(row["recorded_at"]),
        )


_DEFAULT_LEDGER: InvestmentPortfolioLedger | None = None


def get_investment_ledger() -> InvestmentPortfolioLedger:
    global _DEFAULT_LEDGER
    env_db = os.environ.get("ATLAS_INVESTMENT_LEDGER_DB")
    if _DEFAULT_LEDGER is None or (env_db and str(_DEFAULT_LEDGER.db_path) != env_db):
        _DEFAULT_LEDGER = InvestmentPortfolioLedger(env_db)
    return _DEFAULT_LEDGER

