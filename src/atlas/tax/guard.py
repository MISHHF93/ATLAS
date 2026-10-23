"""Optional pre-trade superficial-loss guard (RiskEngine hook). mode: 'warn' | 'block'."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from atlas.tax.engine import TaxEngine
from atlas.tax.events import Trade


class SuperficialLossGuard:
    name = "superficial_loss_guard"

    def __init__(self, engine: TaxEngine, events: list, entity: str, mode: str = "warn",
                 today: Callable[[], date] | None = None):
        if mode not in ("warn", "block"):
            raise ValueError("mode must be warn|block")
        from atlas.control.policy.venues import as_of_date
        self.engine, self.events, self.entity, self.mode, self.today = engine, events, entity, mode, today or as_of_date

    def check(self, prop: str, side: str, unit_value_cad: Decimal | None) -> list[str]:
        d = self.today()
        rep = self.engine.run(self.events)
        aff = self.engine.aff.affiliated(self.entity)
        msgs = []
        if side == "buy":
            for disp in rep.dispositions:
                if disp.entity in aff and disp.property == prop and disp.gain < 0 and timedelta(0) <= d - disp.date <= timedelta(days=30):
                    msgs.append(f"buying {prop} within 30 days of a loss sale on {disp.date} ({disp.entity}) would make that loss superficial")
        else:
            tp = self.engine.entities[self.entity].taxpayer
            avg = rep.acb_per_unit(tp, prop)
            if unit_value_cad is not None and avg > 0 and unit_value_cad < avg:
                recent = [e for e in self.events if isinstance(e, Trade) and e.side == "buy" and e.property == prop
                          and e.entity in aff and timedelta(0) <= d - e.ts.date() <= timedelta(days=30)]
                if recent:
                    msgs.append(f"selling {prop} at a loss with an affiliated purchase in the last 30 days: loss likely superficial")
                else:
                    msgs.append(f"selling {prop} at a loss: do not repurchase (any affiliated account) for 30 days")
        return msgs

    def __call__(self, intent, state):
        prop = intent.issuer or intent.symbol
        unit = None
        if intent.reference_price:
            unit = Decimal(str(intent.reference_price)) * Decimal(str(intent.fx_rate_to_base))
        try:
            msgs = self.check(prop, intent.side, unit)
        except Exception as e:  # noqa: BLE001  tax calc problem: surface, fail closed only in block mode
            msgs = [f"superficial-loss check unavailable: {e}"]
        return (msgs, []) if self.mode == "block" else ([], msgs)
