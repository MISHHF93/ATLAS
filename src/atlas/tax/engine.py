"""ACB + superficial-loss engine. Record keeping only — NOT tax advice.

Rules implemented (simplified; see README):
* ACB = average cost per identical property, pooled per taxpayer across venues and
  non-registered accounts, in CAD (Bank of Canada rate per fill, source stored).
  Buy: ACB += qty*price*fx + fees. Sell: cost = ACB * qty/pool_qty; gain = proceeds - outlays - cost.
* Superficial loss (s.54 / s.40(2)(g)(i)): for a loss on date D, if the taxpayer or an
  affiliated entity acquires identical property in [D-30, D+30] and an affiliated entity
  holds it at the end of D+30, denied = loss * min(S, P, B) / S
  (S sold, P acquired in window, B held at window end). The denied loss is added to the
  ACB of the substituted property (s.53(1)(f)) of the holder; if only a registered plan
  holds it, the loss is permanently denied; if the disposer is a corporation it is
  recorded as suspended (s.40(3.4)) for CPA treatment.
* Crypto-to-crypto swaps are dispositions at FMV received; fees paid in crypto are
  dispositions of the fee asset; transfers between the same taxpayer's wallets are not
  dispositions but must link; staking rewards are income with ACB = FMV.
"""
from __future__ import annotations

import csv
import hashlib
import io
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from atlas.tax.entities import Affiliations, Entity
from atlas.tax.events import Dividend, Income, Swap, Trade, Transfer
from atlas.tax.fx import BocFxProvider

from atlas.ops.timez import TORONTO  # noqa: E402
D0 = Decimal(0)
CENT = Decimal("0.01")
WINDOW = timedelta(days=30)
INCLUSION_RATE = {2026: Decimal("0.5")}  # capital gains inclusion rate by tax year (verify annually)
T1135_THRESHOLD = Decimal(100_000)
US_TREATY_RATE = Decimal("0.15")
ENGINE_VERSION = "tax-engine-0.1"


def q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def tdate(ts: datetime) -> date:
    if ts.tzinfo is None:
        raise ValueError("timestamps must be tz-aware")
    return ts.astimezone(TORONTO).date()


@dataclass
class _Op:
    seq: int
    d: date
    kind: str            # acq | disp | move
    entity: str
    prop: str
    qty: Decimal
    amount: Decimal      # cost (acq) or proceeds (disp)
    outlays: Decimal
    src: str
    asset_type: str
    venue: str = ""
    foreign: bool = False
    automated: bool = True
    note: str = ""
    fx_source: str = ""


@dataclass
class Disposition:
    id: str
    entity: str
    taxpayer: str
    date: date
    property: str
    asset_type: str
    qty: Decimal
    proceeds: Decimal
    acb: Decimal
    outlays: Decimal
    gain: Decimal                 # before superficial-loss denial
    denied_loss: Decimal = D0     # positive amount denied
    treatment: str = ""           # "", "added_to_acb:<entity>", "permanently_denied(registered)", "suspended_40(3.4)"
    fx_source: str = ""
    note: str = ""

    @property
    def allowable(self) -> Decimal:
        return self.gain + self.denied_loss


@dataclass
class TaxReport:
    dispositions: list[Disposition] = field(default_factory=list)
    income: list[dict] = field(default_factory=list)
    dividends: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pools: dict[tuple[str, str], tuple[Decimal, Decimal]] = field(default_factory=dict)
    t1135: dict[tuple[str, int], dict] = field(default_factory=dict)
    evidence: dict[tuple[str, int], dict] = field(default_factory=dict)
    fills_fx: list[dict] = field(default_factory=list)
    input_hash: str = ""

    def acb(self, taxpayer: str, prop: str) -> tuple[Decimal, Decimal]:
        qty, acb = self.pools.get((taxpayer, prop), (D0, D0))
        return qty, q(acb)

    def acb_per_unit(self, taxpayer: str, prop: str) -> Decimal:
        qty, acb = self.pools.get((taxpayer, prop), (D0, D0))
        return (acb / qty) if qty else D0

    # ---------------------------------------------------------------- exports
    def schedule3(self, taxpayer: str, year: int) -> dict[str, dict[str, Decimal]]:
        out: dict[str, dict[str, Decimal]] = {}
        rate = INCLUSION_RATE.get(year, Decimal("0.5"))
        for d in self.dispositions:
            if d.taxpayer != taxpayer or d.date.year != year:
                continue
            cat = "crypto" if d.asset_type == "crypto" else "shares_and_units"
            s = out.setdefault(cat, defaultdict(lambda: D0))
            s["proceeds"] += d.proceeds; s["acb"] += d.acb; s["outlays"] += d.outlays
            s["gains"] += max(d.allowable, D0); s["losses"] += min(d.allowable, D0); s["denied_superficial"] += d.denied_loss
        for cat, s in out.items():
            s["net"] = s["gains"] + s["losses"]
            s["taxable_if_capital"] = q(s["net"] * rate) if s["net"] > 0 else D0
            out[cat] = {k: q(v) for k, v in s.items()}
        return out

    def t5008_csv(self, taxpayer: str | None = None, year: int | None = None) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# NOT TAX ADVICE - record-keeping export for review by a CPA", ENGINE_VERSION, f"input_sha256={self.input_hash}"])
        w.writerow(["taxpayer", "entity", "date", "property", "asset_type", "quantity", "proceeds_cad", "acb_cad", "outlays_cad",
                    "gain_loss_cad", "superficial_denied_cad", "allowable_gain_loss_cad", "treatment", "fx_source", "disposition_id"])
        for d in self.dispositions:
            if (taxpayer and d.taxpayer != taxpayer) or (year and d.date.year != year):
                continue
            w.writerow([d.taxpayer, d.entity, d.date.isoformat(), d.property, d.asset_type, d.qty, q(d.proceeds), q(d.acb),
                        q(d.outlays), q(d.gain), q(d.denied_loss), q(d.allowable), d.treatment, d.fx_source, d.id])
        return buf.getvalue()

    def schedule3_csv(self, taxpayer: str, year: int) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# NOT TAX ADVICE - Schedule 3-style summary", taxpayer, year, ENGINE_VERSION])
        cols = ["proceeds", "acb", "outlays", "gains", "losses", "denied_superficial", "net", "taxable_if_capital"]
        w.writerow(["category"] + cols)
        for cat, s in self.schedule3(taxpayer, year).items():
            w.writerow([cat] + [s[c] for c in cols])
        return buf.getvalue()

    def evidence_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["trades", "automated_trades", "buy_value_cad", "sell_value_cad", "turnover_ratio", "avg_holding_days",
                "median_holding_days", "pct_held_under_30d", "pct_held_under_1d", "registered_trades", "flags"]
        w.writerow(["# business-vs-capital EVIDENCE for a CPA decision; not a determination"])
        w.writerow(["entity", "year"] + cols)
        for (ent, yr), e in sorted(self.evidence.items()):
            w.writerow([ent, yr] + [e.get(c) if c != "flags" else "|".join(e["flags"]) for c in cols])
        return buf.getvalue()


class TaxEngine:
    def __init__(self, entities: list[Entity], affiliations: Affiliations | None = None, fx: BocFxProvider | None = None,
                 foreign_properties: set[str] | None = None, include_crypto_in_t1135: bool = False):
        self.entities = {e.id: e for e in entities}
        self.aff = affiliations or Affiliations()
        self.fx = fx
        self.foreign = set(foreign_properties or set())
        self.include_crypto_t1135 = include_crypto_in_t1135

    # ---------------------------------------------------------------- normalise
    def _fx(self, ccy: str, d: date, given=None):
        if given is not None:
            return given
        if ccy == "CAD":
            from atlas.tax.fx import FxQuote
            return FxQuote(Decimal(1), "identity (CAD)", d)
        if self.fx is None:
            raise ValueError(f"FX needed for {ccy} on {d} but no provider configured (fail closed)")
        return self.fx.quote(ccy, d)

    def _normalise(self, events, rep: TaxReport) -> list[_Op]:
        ops: list[_Op] = []
        seq = 0

        def add(**kw):
            nonlocal seq
            ops.append(_Op(seq=seq, **kw)); seq += 1

        transfers: dict[str, list[Transfer]] = defaultdict(list)
        for ev in sorted(events, key=lambda e: e.ts):
            if ev.entity not in self.entities:
                raise ValueError(f"unknown entity {ev.entity!r} in {ev.id}")
            d = tdate(ev.ts)
            if isinstance(ev, Trade):
                fxq = self._fx(ev.currency, d, ev.fx)
                rep.fills_fx.append({"id": ev.id, "currency": ev.currency, "rate": fxq.rate, "source": fxq.source})
                gross = ev.qty * ev.price * fxq.rate
                fee = ev.fee * fxq.rate
                if ev.crypto_fee:
                    cf = ev.crypto_fee
                    add(d=d, kind="disp", entity=ev.entity, prop=cf.property, qty=cf.qty, amount=cf.fmv_cad, outlays=D0,
                        src=ev.id + ":fee", asset_type="crypto", venue=ev.venue, automated=ev.automated, note="fee paid in crypto")
                    fee += cf.fmv_cad
                foreign = ev.foreign or ev.property in self.foreign
                if foreign:
                    self.foreign.add(ev.property)
                if ev.side == "buy":
                    add(d=d, kind="acq", entity=ev.entity, prop=ev.property, qty=ev.qty, amount=gross + fee, outlays=D0, src=ev.id,
                        asset_type=ev.asset_type, venue=ev.venue, foreign=foreign, automated=ev.automated, fx_source=fxq.source)
                else:
                    add(d=d, kind="disp", entity=ev.entity, prop=ev.property, qty=ev.qty, amount=gross, outlays=fee, src=ev.id,
                        asset_type=ev.asset_type, venue=ev.venue, foreign=foreign, automated=ev.automated, fx_source=fxq.source)
            elif isinstance(ev, Swap):
                outl = D0
                if ev.crypto_fee:
                    cf = ev.crypto_fee
                    add(d=d, kind="disp", entity=ev.entity, prop=cf.property, qty=cf.qty, amount=cf.fmv_cad, outlays=D0,
                        src=ev.id + ":fee", asset_type="crypto", venue=ev.venue, note="fee paid in crypto")
                    outl = cf.fmv_cad
                add(d=d, kind="disp", entity=ev.entity, prop=ev.give_property, qty=ev.give_qty, amount=ev.fmv_cad, outlays=outl,
                    src=ev.id, asset_type="crypto", venue=ev.venue, automated=ev.automated, note=f"swap -> {ev.get_property}")
                add(d=d, kind="acq", entity=ev.entity, prop=ev.get_property, qty=ev.get_qty, amount=ev.fmv_cad, outlays=D0,
                    src=ev.id, asset_type="crypto", venue=ev.venue, automated=ev.automated, note=f"swap <- {ev.give_property}")
            elif isinstance(ev, Transfer):
                transfers[ev.transfer_id].append(ev)
                sign = -1 if ev.direction == "out" else 1
                add(d=d, kind="move", entity=ev.entity, prop=ev.property, qty=Decimal(sign) * ev.qty, amount=D0, outlays=D0,
                    src=ev.id, asset_type="crypto", venue=ev.venue, note=f"transfer {ev.transfer_id}")
                if ev.direction == "out" and ev.network_fee_qty > 0:
                    add(d=d, kind="disp", entity=ev.entity, prop=ev.property, qty=ev.network_fee_qty, amount=ev.network_fee_fmv_cad,
                        outlays=D0, src=ev.id + ":netfee", asset_type="crypto", venue=ev.venue, note="network fee")
            elif isinstance(ev, Income):
                rep.income.append({"id": ev.id, "entity": ev.entity, "date": d, "property": ev.property, "qty": ev.qty,
                                   "fmv_cad": q(ev.fmv_cad), "kind": ev.kind})
                add(d=d, kind="acq", entity=ev.entity, prop=ev.property, qty=ev.qty, amount=ev.fmv_cad, outlays=D0,
                    src=ev.id, asset_type="crypto", venue=ev.venue, note=f"{ev.kind} income")
            elif isinstance(ev, Dividend):
                self._dividend(ev, d, rep)
        # transfer linking
        for tid, legs in transfers.items():
            outs = [t for t in legs if t.direction == "out"]
            ins = [t for t in legs if t.direction == "in"]
            if len(outs) != 1 or len(ins) != 1:
                rep.warnings.append(f"transfer {tid}: unlinked legs (out={len(outs)}, in={len(ins)}) - possible missing record or disposition")
                continue
            o, i = outs[0], ins[0]
            if self.entities[o.entity].taxpayer != self.entities[i.entity].taxpayer:
                rep.warnings.append(f"transfer {tid}: between different taxpayers ({o.entity} -> {i.entity}) - may be a disposition/gift; CPA review")
            if o.property != i.property or o.qty - o.network_fee_qty != i.qty:
                rep.warnings.append(f"transfer {tid}: quantity/property mismatch (out {o.qty}-{o.network_fee_qty} fee vs in {i.qty})")
        return ops

    def _dividend(self, ev: Dividend, d: date, rep: TaxReport) -> None:
        ent = self.entities[ev.entity]
        fxq = self._fx(ev.currency, d, ev.fx)
        rate = (ev.withheld / ev.gross) if ev.gross else D0
        warn = ""
        if ev.country == "US":
            if ent.kind == "rrsp" and ev.withheld > 0:
                warn = "RRSP/RRIF is generally exempt from US withholding under the treaty - check W-8BEN/broker setup"
            elif rate > US_TREATY_RATE + Decimal("0.005"):
                warn = (f"US withholding {rate:.0%} > 15% treaty rate - check W-8BEN/W-8BEN-E on file at the broker"
                        if ent.w8ben_on_file else f"US withholding {rate:.0%}: no W-8BEN/W-8BEN-E on file")
            if ent.kind == "tfsa" and ev.withheld > 0:
                warn = (warn + "; " if warn else "") + "TFSA: US withholding not recoverable (no foreign tax credit)"
        rec = {"id": ev.id, "entity": ev.entity, "taxpayer": ent.taxpayer, "date": d, "property": ev.property, "country": ev.country,
               "gross": ev.gross, "withheld": ev.withheld, "currency": ev.currency, "withholding_rate": q(rate * 100),
               "gross_cad": q(ev.gross * fxq.rate), "withheld_cad": q(ev.withheld * fxq.rate), "fx_source": fxq.source, "warning": warn}
        rep.dividends.append(rec)
        if warn:
            rep.warnings.append(f"dividend {ev.id}: {warn}")

    # ---------------------------------------------------------------- run
    def run(self, events) -> TaxReport:
        rep = TaxReport()
        h = hashlib.sha256()
        for e in sorted(events, key=lambda e: (e.ts, e.id)):
            h.update(repr(e).encode())
        rep.input_hash = h.hexdigest()
        ops = self._normalise(events, rep)
        # quantity series per entity/property (for window acquisitions & holdings)
        series: dict[tuple[str, str], list[tuple[date, Decimal, str]]] = defaultdict(list)
        for o in ops:
            delta = o.qty if o.kind in ("acq",) else (-o.qty if o.kind == "disp" else o.qty)
            series[(o.entity, o.prop)].append((o.d, delta, o.kind))

        def held_at(ent: str, prop: str, end: date) -> Decimal:
            return sum((dq for dd, dq, _ in series[(ent, prop)] if dd <= end), D0)

        def acquired_between(ent: str, prop: str, a: date, b: date) -> Decimal:
            return sum((dq for dd, dq, k in series[(ent, prop)] if k == "acq" and a <= dd <= b), D0)

        pools: dict[tuple[str, str], list[Decimal]] = defaultdict(lambda: [D0, D0])
        pending: list[dict] = []
        lots: dict[tuple[str, str], deque] = defaultdict(deque)
        ev_stats: dict[tuple[str, int], dict] = defaultdict(lambda: {"trades": 0, "automated_trades": 0, "buy_value_cad": D0,
                                                                     "sell_value_cad": D0, "holding_days": [], "registered_trades": 0,
                                                                     "cost_samples": []})
        foreign_peak: dict[tuple[str, int], dict] = {}

        def pool_key(ent_id: str) -> str:
            e = self.entities[ent_id]
            return f"REG:{e.id}" if e.registered else e.taxpayer

        for o in ops:
            ent = self.entities[o.entity]
            pk = (pool_key(o.entity), o.prop)
            pool = pools[pk]
            st = ev_stats[(o.entity, o.d.year)]
            if o.kind == "move":
                continue  # same-taxpayer transfer: pool unchanged (fees handled as separate disposition)
            if o.kind == "acq":
                pool[0] += o.qty; pool[1] += o.amount
                lots[(o.entity, o.prop)].append([o.d, o.qty])
                st["trades"] += 1; st["buy_value_cad"] += o.amount; st["automated_trades"] += int(o.automated)
                st["registered_trades"] += int(ent.registered)
                for p in list(pending):
                    if p["pool"] == pk and o.d <= p["window_end"]:
                        pool[1] += p["amount"]; pending.remove(p)
            else:  # disposition
                st["trades"] += 1; st["sell_value_cad"] += o.amount; st["automated_trades"] += int(o.automated)
                st["registered_trades"] += int(ent.registered)
                # holding period evidence (FIFO lots, evidence only)
                need = o.qty
                lq = lots[(o.entity, o.prop)]
                while need > 0 and lq:
                    lot = lq[0]; take = min(lot[1], need)
                    st["holding_days"].append(((o.d - lot[0]).days, take))
                    lot[1] -= take; need -= take
                    if lot[1] <= 0:
                        lq.popleft()
                if pool[0] <= 0 or o.qty > pool[0] + Decimal("1e-12"):
                    rep.warnings.append(f"{o.src}: disposing {o.qty} {o.prop} but pool holds {pool[0]} - missing acquisition record?")
                cost = (pool[1] * min(o.qty, pool[0]) / pool[0]) if pool[0] > 0 else D0
                pool[0] -= o.qty; pool[1] -= cost
                if pool[0] <= 0:
                    pool[0], pool[1] = D0, D0
                if ent.registered:
                    continue  # no gain/loss reporting inside registered plans
                gain = o.amount - o.outlays - cost
                disp = Disposition(o.src, o.entity, ent.taxpayer, o.d, o.prop, o.asset_type, o.qty, o.amount, cost, o.outlays,
                                   gain, fx_source=o.fx_source, note=o.note)
                if gain < 0:
                    self._superficial(disp, o, acquired_between, held_at, pools, pool_key, pending)
                rep.dispositions.append(disp)
            # T1135 (taxable, non-registered only)
            if not ent.registered and (o.prop in self.foreign or (self.include_crypto_t1135 and o.asset_type == "crypto")):
                tp = ent.taxpayer
                total = sum((v[1] for (k, p), v in pools.items() if k == tp and
                             (p in self.foreign or (self.include_crypto_t1135 and p in self._crypto_props(ops)))), D0)
                cur = foreign_peak.setdefault((tp, o.d.year), {"peak_cost_cad": D0, "peak_date": None})
                if total > cur["peak_cost_cad"]:
                    cur["peak_cost_cad"], cur["peak_date"] = total, o.d
            st["cost_samples"].append(sum((v[1] for (k, _), v in pools.items() if k == pool_key(o.entity)), D0))

        for p in pending:
            pool = pools[p["pool"]]
            if pool[0] > 0:
                pool[1] += p["amount"]
            else:
                rep.warnings.append(f"superficial loss {p['source']}: substituted property not found in pool {p['pool']}; denied amount unallocated")
        rep.pools = {k: (v[0], v[1]) for k, v in pools.items() if not k[0].startswith("REG:")}
        for k, v in foreign_peak.items():
            rep.t1135[k] = {"peak_cost_cad": q(v["peak_cost_cad"]), "peak_date": v["peak_date"],
                            "t1135_required": v["peak_cost_cad"] > T1135_THRESHOLD}
        rep.evidence = {k: self._evidence(k, v) for k, v in ev_stats.items()}
        return rep

    def _crypto_props(self, ops):
        return {o.prop for o in ops if o.asset_type == "crypto"}

    def _superficial(self, disp, o, acquired_between, held_at, pools, pool_key, pending) -> None:
        start, end = o.d - WINDOW, o.d + WINDOW
        aff = self.aff.affiliated(o.entity)
        purchased = sum((acquired_between(e, o.prop, start, end) for e in aff), D0)
        holders = {e: held_at(e, o.prop, end) for e in aff}
        held_end = sum((max(v, D0) for v in holders.values()), D0)
        n = min(o.qty, purchased, held_end)
        if n <= 0:
            return
        loss = -disp.gain
        denied = loss * n / o.qty
        disp.denied_loss = denied
        disposer = self.entities[o.entity]
        if disposer.kind == "corporation":
            disp.treatment = "suspended_40(3.4) - CPA review"
            return
        # choose holder of substituted property: self, same taxpayer, other taxable affiliate, else registered
        order = sorted((e for e, v in holders.items() if v > 0),
                       key=lambda e: (e != o.entity, self.entities[e].taxpayer != disposer.taxpayer, self.entities[e].registered))
        target = order[0]
        if self.entities[target].registered:
            disp.treatment = f"permanently_denied(registered:{target})"
            return
        pk = (pool_key(target), o.prop)
        disp.treatment = f"added_to_acb:{target}"
        if pools[pk][0] > 0:
            pools[pk][1] += denied
        else:
            pending.append({"pool": pk, "amount": denied, "window_end": end, "source": disp.id})

    @staticmethod
    def _evidence(key, s) -> dict:
        hd = s["holding_days"]
        total_q = sum((qq for _, qq in hd), D0)
        avg = float(sum((Decimal(dd) * qq for dd, qq in hd), D0) / total_q) if total_q else None
        med = median([dd for dd, _ in hd]) if hd else None
        u30 = float(sum((qq for dd, qq in hd if dd < 30), D0) / total_q * 100) if total_q else None
        u1 = float(sum((qq for dd, qq in hd if dd < 1), D0) / total_q * 100) if total_q else None
        avg_cost = (sum(s["cost_samples"], D0) / len(s["cost_samples"])) if s["cost_samples"] else D0
        turnover = float(s["sell_value_cad"] / avg_cost) if avg_cost > 0 else None
        flags = []
        if s["automated_trades"]:
            flags.append("automated trading (bot) - factor toward business income")
        if u30 is not None and u30 > 50:
            flags.append("majority of quantity held < 30 days")
        if turnover is not None and turnover > 4:
            flags.append(f"high turnover ({turnover:.1f}x)")
        if s["registered_trades"]:
            flags.append("trading inside a registered plan (TFSA business-income risk if TFSA)")
        return {"trades": s["trades"], "automated_trades": s["automated_trades"], "buy_value_cad": q(s["buy_value_cad"]),
                "sell_value_cad": q(s["sell_value_cad"]), "turnover_ratio": None if turnover is None else round(turnover, 2),
                "avg_holding_days": None if avg is None else round(avg, 1), "median_holding_days": med,
                "pct_held_under_30d": None if u30 is None else round(u30, 1), "pct_held_under_1d": None if u1 is None else round(u1, 1),
                "registered_trades": s["registered_trades"], "flags": flags}
