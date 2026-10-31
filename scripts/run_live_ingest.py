#!/usr/bin/env python
"""Run the ATLAS live ingest service (Coinbase/Kraken websockets + Yahoo polling) into the feed store.

    PYTHONPATH=src python scripts/run_live_ingest.py [--db var/feeds/atlas_feed.sqlite] [--duration SECONDS]
Writes its PID to var/feeds/live_ingest.pid (stop it with ``kill $(cat var/feeds/live_ingest.pid)``).

This process does not spawn another interpreter. On Windows, starting it with a venv
``Scripts\\python.exe`` shows a redirector parent plus the base ``Python312`` child; that
pair is the venv launcher (``PC/venvlauncher.c``), and the pid file records the child
(``os.getpid()``), which is the process doing the ingest.
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.feeds.feed import DEFAULT_STORE  # noqa: E402
from atlas.feeds.live import LiveIngest  # noqa: E402
from atlas.feeds.store import FeedStore  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_STORE)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--open-poll", type=float, default=30)
    ap.add_argument("--closed-poll", type=float, default=900)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    pid = Path(a.db).parent / "live_ingest.pid"
    pid.parent.mkdir(parents=True, exist_ok=True)
    pid.write_text(str(os.getpid()))
    try:
        asyncio.run(LiveIngest(FeedStore(a.db), open_poll=a.open_poll, closed_poll=a.closed_poll).run(a.duration))
    finally:
        if pid.exists() and pid.read_text() == str(os.getpid()):
            pid.unlink()


if __name__ == "__main__":
    main()
