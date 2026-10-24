"""Before/after: StrategyBacktester legacy (instant fill, touch exits) vs paper realism on real feed bars.
Usage: ATLAS_FEED_DB=... python scripts/backtester_realism_compare.py [INSTRUMENT] [INTERVAL] [N_BARS]"""
import json, os, sqlite3, sys
import pandas as pd
from atlas.research.backtester import StrategyBacktester

inst, iv, n = (sys.argv[1:4] + ["BTCUSDT", "15m", "3000"][len(sys.argv[1:4]):])
c = sqlite3.connect(os.environ["ATLAS_FEED_DB"])
rows = c.execute("""SELECT event_time, open, high, low, close, volume FROM bar_revisions b WHERE instrument=? AND interval=?
  AND confirmed=1 AND receipt_time=(SELECT MAX(receipt_time) FROM bar_revisions WHERE provider=b.provider AND
  instrument=b.instrument AND interval=b.interval AND event_time=b.event_time) GROUP BY event_time
  ORDER BY event_time DESC LIMIT ?""", (inst, iv, int(n))).fetchall()
df = pd.DataFrame(rows[::-1], columns=["t", "open", "high", "low", "close", "volume"])
unit = "ms" if df.t.max() > 1e12 else "s"
df["timestamp"] = pd.to_datetime(df.t, unit=unit, utc=True)
sessions = sorted({ts.normalize() for ts in df.timestamp})
out = {"instrument": inst, "interval": iv, "bars": len(df), "from": str(df.timestamp.iloc[0]), "to": str(df.timestamp.iloc[-1])}
for name, b in (("legacy", StrategyBacktester(None, None, realism=None)), ("paper_realism", StrategyBacktester(None, None))):
    o = b.run_backtest(inst, df, sessions)
    perf = b.evaluate_performance(o)
    perf.update(unfilled=b.unfilled, mean_fill_ratio=(sum(x.fill_ratio for x in o) / len(o)) if o else None,
                net_bps=sum(x.pnl_bps for x in o))
    out[name] = perf
print(json.dumps(out, indent=1, default=float))
