"""Run the 15m technique-selector + range-break hypothesis evaluation on cached real bars (research only).
Usage: python scripts/run_selector_evidence.py [cache_dir]  -> docs/spec/evidence/technique-selector-<date>.json"""
import json
import sys
from datetime import date
from pathlib import Path

from atlas.research.technique_selection import run

cache = Path(sys.argv[1] if len(sys.argv) > 1 else "var/evidence_cache_15m")
out = run(cache)
p = Path("docs/spec/evidence") / f"technique-selector-{date.today().isoformat()}.json"
p.write_text(json.dumps(out, indent=1, default=str))
print(p)
