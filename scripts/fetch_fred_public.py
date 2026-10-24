"""Fetch keyless FRED series into the feed observations table with conservative release lags (section 22).
Usage: ATLAS_FEED_DB=... python scripts/fetch_fred_public.py [SERIES ...]"""
import json
import sys
if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)



def main() -> int:
    from atlas.feeds.feed import get_feed
    from atlas.feeds.providers import fred_public as F
    store = get_feed().store
    out = {}
    for sid in (sys.argv[1:] or list(F.SERIES)):
        obs = F.fetch(sid)
        out[sid] = {"n": len(obs), "inserted": store.ingest_observations(obs), "first": obs[0].date if obs else None,
                    "last": obs[-1].date if obs else None, "last_available_from": obs[-1].realtime_start if obs else None}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
