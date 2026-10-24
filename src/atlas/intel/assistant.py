"""Grounded research assistant: deterministic BM25 retrieval (ml.retrieval) over docs/ + lab reports, returning
an extractive answer whose every sentence carries an evidence ID. Evidence IDs are content-addressed
(EV-<sha256(cite|text)[:10]>), so the same corpus + query always yields the same IDs.
The LLM adapter (ai.assistant.providers) is reported but NEVER invoked here; without a key it is disabled, and even
with a key this endpoint stays deterministic. No answer is produced when nothing is retrieved (no fabrication)."""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from atlas.ml.retrieval import BM25Index, build_index, split_passages


def evidence_id(cite: str, text: str) -> str:
    return "EV-" + hashlib.sha256(f"{cite}|{text}".encode()).hexdigest()[:10]


@lru_cache(maxsize=4)
def _index(repo_root: str, lab_dir: str, stamp: float) -> BM25Index:
    base = build_index(repo_root)
    extra = []
    lab = Path(lab_dir)
    if lab.exists():
        for f in sorted(lab.glob("report_*.md")):
            extra += split_passages(f"lab/{f.name}", f.read_text(errors="replace"))
    return BM25Index(list(base.passages) + extra) if extra else base


def llm_status(env=os.environ) -> dict[str, Any]:
    from atlas.ai.assistant.providers import provider_list
    ps = [p for p in provider_list(env) if p.get("id") != "local"]
    enabled = [p["id"] for p in ps if p.get("enabled")]
    return {"enabled_providers": enabled, "used": False, "state": "disabled_no_key" if not enabled else "available_not_used",
            "execution_permission": "none"}


def ask(query: str, k: int = 5, repo_root: str = ".", lab_dir: str | None = None) -> dict[str, Any]:
    lab_dir = lab_dir or os.environ.get("ATLAS_LAB_DIR", "var/lab")
    lab = Path(lab_dir)
    stamp = max((f.stat().st_mtime for f in lab.glob("report_*.md")), default=0.0) if lab.exists() else 0.0
    hits = _index(str(Path(repo_root).resolve()), str(lab), stamp).search(query, k=k)
    ev = [{"id": evidence_id(h["cite"], h["snippet"]), **h} for h in hits]
    answer = [{"text": e["snippet"], "evidence": [e["id"]]} for e in ev[:3]]
    return {"query": query, "mode": "deterministic_extractive", "answer": answer, "evidence": ev,
            "status": "ok" if ev else "no_evidence", "note": None if ev else "nothing in the corpus matched; no answer generated",
            "llm": llm_status()}
