"""Creator and wallet behavior research engine.

Separates verified on-chain facts (balances, creator launch history, trade sizes) from
heuristic risk indicators (co-funding cluster estimates, synchronized early-slot buying).
Never claims that an unverified heuristic cluster proves malicious coordination.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

CLUSTER_DISCLAIMER = (
    "Heuristic wallet cluster indicators measure funding-source and slot-timing similarity only; "
    "they do NOT prove common ownership or malicious coordination."
)


@dataclass(frozen=True)
class HolderEntry:
    wallet: str
    balance_tokens: float
    pct_of_supply: float
    is_creator: bool = False
    is_pool_or_curve: bool = False
    funded_by: str | None = None
    first_buy_slot: int | None = None


@dataclass(frozen=True)
class WalletTradeSample:
    signature: str
    slot: int
    event_time: float
    wallet: str
    side: str  # "buy" | "sell"
    quote_amount_sol: float
    token_amount: float
    price_quote: float
    is_creator: bool = False


@dataclass(frozen=True)
class WalletIntelligenceReport:
    mint: str
    creator_wallet: str
    verified_on_chain_facts: dict[str, Any]
    heuristic_indicators: dict[str, Any]
    whale_activity: dict[str, Any]
    disclaimer: str = CLUSTER_DISCLAIMER

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_wallet_intelligence(
    *,
    mint: str,
    creator_wallet: str,
    holders: Sequence[HolderEntry],
    trades: Sequence[WalletTradeSample],
    creator_prior_launches: int = 0,
    creator_prior_graduations: int = 0,
    creator_prior_early_dumps: int = 0,
    whale_threshold_sol: float = 5.0,
) -> WalletIntelligenceReport:
    """Analyze creator history, holder concentration, whale flow, and heuristic funding clusters."""
    circulating = [h for h in holders if not h.is_pool_or_curve]
    circulating.sort(key=lambda h: h.pct_of_supply, reverse=True)

    creator_pct = sum(h.pct_of_supply for h in circulating if h.is_creator or h.wallet == creator_wallet)
    top1_pct = circulating[0].pct_of_supply if circulating else 0.0
    top5_pct = sum(h.pct_of_supply for h in circulating[:5])
    top10_pct = sum(h.pct_of_supply for h in circulating[:10])

    # Verified creator trading activity on this token
    creator_sells_sol = sum(t.quote_amount_sol for t in trades if (t.is_creator or t.wallet == creator_wallet) and t.side == "sell")
    creator_buys_sol = sum(t.quote_amount_sol for t in trades if (t.is_creator or t.wallet == creator_wallet) and t.side == "buy")

    # Heuristic cluster estimation: wallets sharing the same non-empty funder address or buying in the exact creation slot
    funder_groups: dict[str, list[HolderEntry]] = {}
    for h in circulating:
        if h.funded_by:
            funder_groups.setdefault(h.funded_by, []).append(h)
    co_funded_pct = sum(
        sum(h.pct_of_supply for h in grp)
        for grp in funder_groups.values()
        if len(grp) >= 2
    )

    slot_groups: dict[int, list[HolderEntry]] = {}
    for h in circulating:
        if h.first_buy_slot is not None:
            slot_groups.setdefault(h.first_buy_slot, []).append(h)
    same_slot_pct = sum(
        sum(h.pct_of_supply for h in grp)
        for grp in slot_groups.values()
        if len(grp) >= 3
    )
    heuristic_cluster_pct = min(100.0, max(co_funded_pct, same_slot_pct))

    # Whale flow analysis
    whale_trades = [t for t in trades if t.quote_amount_sol >= whale_threshold_sol]
    whale_buy_sol = sum(t.quote_amount_sol for t in whale_trades if t.side == "buy")
    whale_sell_sol = sum(t.quote_amount_sol for t in whale_trades if t.side == "sell")
    whale_wallets = sorted({t.wallet for t in whale_trades})

    verified_facts = {
        "creator_wallet": creator_wallet,
        "creator_holding_pct": round(creator_pct, 2),
        "top1_holder_pct": round(top1_pct, 2),
        "top5_holder_pct": round(top5_pct, 2),
        "top10_holder_pct": round(top10_pct, 2),
        "non_pool_holder_count": len(circulating),
        "creator_buys_sol": round(creator_buys_sol, 4),
        "creator_sells_sol": round(creator_sells_sol, 4),
        "creator_prior_launches": int(creator_prior_launches),
        "creator_prior_graduations": int(creator_prior_graduations),
    }

    abandon_rate = (
        round(creator_prior_early_dumps / creator_prior_launches, 4)
        if creator_prior_launches > 0
        else 0.0
    )
    heuristic_indicators = {
        "co_funded_holder_pct": round(co_funded_pct, 2),
        "same_slot_early_buyer_pct": round(same_slot_pct, 2),
        "suspicious_cluster_pct": round(heuristic_cluster_pct, 2),
        "creator_prior_early_dump_rate": abandon_rate,
        "cluster_coordination_proven": False,
    }

    whale_activity = {
        "whale_threshold_sol": whale_threshold_sol,
        "whale_trade_count": len(whale_trades),
        "whale_unique_wallets": len(whale_wallets),
        "whale_buy_sol": round(whale_buy_sol, 4),
        "whale_sell_sol": round(whale_sell_sol, 4),
        "whale_net_flow_sol": round(whale_buy_sol - whale_sell_sol, 4),
    }

    return WalletIntelligenceReport(
        mint=mint,
        creator_wallet=creator_wallet,
        verified_on_chain_facts=verified_facts,
        heuristic_indicators=heuristic_indicators,
        whale_activity=whale_activity,
    )

