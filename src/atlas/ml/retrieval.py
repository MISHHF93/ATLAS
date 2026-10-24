"""Local BM25 retrieval over docs/, evidence and model cards so explanations cite exact passages.

Okapi BM25 (Robertson & Zaragoza 2009, "The Probabilistic Relevance Framework: BM25 and Beyond"):
score(q, d) = sum_t idf(t) · f(t,d)(k1+1) / (f(t,d) + k1(1 - b + b·|d|/avgdl)),  idf = ln(1 + (N - n_t + 0.5)/(n_t + 0.5)).
Passages = markdown sections split on headings, further cut into <= ~120-line windows. No network, no embeddings.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
STOP = frozenset("a an and are as at be by for from has have in is it its of on or that the this to was were will with not no "
                 "we our you your can may if then than so but into each per all any".split())
K1, B = 1.5, 0.75
EXTS = {".md", ".txt", ".csv", ".json"}


def tokenize(text: str) -> list[str]:
    out = []
    for t in TOKEN.findall(text.lower()):
        if t in STOP or len(t) < 2:
            continue
        out.append(t)
        if any(c in t for c in "._-"):
            out += [p for p in re.split(r"[._-]", t) if len(p) > 1 and p not in STOP]
    return out


@dataclass(frozen=True)
class Passage:
    path: str
    heading: str
    line_start: int
    line_end: int
    text: str


def split_passages(path: str, text: str, max_lines: int = 120) -> list[Passage]:
    lines = text.splitlines()
    out, head, start = [], "", 0
    def flush(end: int):
        for s in range(start, end, max_lines):
            e = min(end, s + max_lines)
            body = "\n".join(lines[s:e]).strip()
            if body:
                out.append(Passage(path, head, s + 1, e, body))
    for i, ln in enumerate(lines):
        if ln.startswith("#"):
            flush(i)
            head, start = ln.lstrip("#").strip(), i
    flush(len(lines))
    return out


class BM25Index:
    def __init__(self, passages: Iterable[Passage]):
        self.passages = list(passages)
        self.tf = [Counter(tokenize(p.heading + " " + p.text)) for p in self.passages]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        df = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(self.passages)
        self.idf = {t: math.log(1 + (n - k + 0.5) / (k + 0.5)) for t, k in df.items()}

    def search(self, query: str, k: int = 5) -> list[dict]:
        q = list(dict.fromkeys(tokenize(query)))
        scored = []
        for i, c in enumerate(self.tf):
            s = 0.0
            for t in q:
                f = c.get(t)
                if f:
                    s += self.idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * self.len[i] / (self.avg or 1)))
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        res = []
        for s, i in scored[:k]:
            p = self.passages[i]
            res.append({"score": round(s, 4), "path": p.path, "heading": p.heading, "line_start": p.line_start,
                        "line_end": p.line_end, "snippet": _snippet(p.text, q), "cite": f"{p.path}#L{p.line_start}-L{p.line_end}"})
        return res


def _snippet(text: str, q: list[str], width: int = 320) -> str:
    low = text.lower()
    pos = min([low.find(t) for t in q if low.find(t) >= 0] or [0])
    s = max(0, pos - width // 3)
    return (("…" if s else "") + text[s:s + width].replace("\n", " ") + ("…" if s + width < len(text) else ""))


def corpus_files(repo_root: str | Path, registry_root: str | Path | None = None) -> list[Path]:
    r = Path(repo_root)
    files = [p for p in sorted((r / "docs").rglob("*")) if p.suffix in EXTS and p.is_file() and p.stat().st_size < 2_000_000]
    if registry_root and Path(registry_root).exists():
        files += sorted(Path(registry_root).glob("*/model_card.md"))
    return files


def build_index(repo_root: str | Path = ".", registry_root: str | Path | None = None) -> BM25Index:
    r = Path(repo_root).resolve()
    ps = []
    for f in corpus_files(r, registry_root):
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        try:
            rel = str(f.resolve().relative_to(r))
        except ValueError:
            rel = str(f)
        ps += split_passages(rel, txt)
    return BM25Index(ps)


def explain_query(detector: str | None, reasons: Iterable[str] = (), extra: str = "") -> str:
    parts = ["meta-label", "calibration", "conformal", "abstain"]
    if detector:
        parts += [detector, detector.replace("_", " ")]
    parts += list(reasons)
    return " ".join(parts) + " " + extra
