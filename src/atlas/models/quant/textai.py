"""Finance text classifiers for the news VETO / DOWNSIZE stage. Offline only; advisory only.

Providers (best available first):
  finbert        ProsusAI/finbert (transformers, local cache)
  distilroberta  mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis (local cache)
  llm            small instruction LLM classifier via the existing HttpLLM provider (disabled unless env configured)
  lexicon        always-available finance lexicon fallback (Loughran-McDonald-style word lists, tiny subset)
Outputs a sentiment in [-1, 1] per headline. The recipe/pipeline may only use it to veto or shrink a BUY;
it can never create, enlarge or flip a trade. Headlines are untrusted text: sanitised, truncated, never executed.
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib.util
import os
import re

from atlas.models.quant.modelcard import ModelCard

NEG = {"loss", "losses", "lawsuit", "fraud", "downgrade", "default", "bankruptcy", "plunge", "plunges", "miss", "misses", "probe",
       "recall", "halt", "halted", "weak", "warning", "cut", "cuts", "decline", "declines", "investigation", "restatement", "layoffs"}
POS = {"beat", "beats", "upgrade", "record", "growth", "surge", "surges", "profit", "raises", "strong", "approval", "wins",
       "outperform", "dividend", "buyback", "expands"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def clean(text: str, n: int = 400) -> str:
    return _CTRL.sub(" ", str(text))[:n]


class Lexicon:
    name = "lexicon"

    def available(self):
        return True, "ok"

    def score(self, texts: list[str]) -> list[float]:
        out = []
        for t in texts:
            w = re.findall(r"[a-z]+", clean(t).lower())
            p, n = sum(x in POS for x in w), sum(x in NEG for x in w)
            out.append(0.0 if p + n == 0 else (p - n) / (p + n))
        return out


class HFClassifier:
    def __init__(self, name: str, repo: str):
        self.name, self.repo, self._pipe = name, repo, None

    def available(self):
        if importlib.util.find_spec("transformers") is None:
            return False, "transformers not installed"
        from atlas.models.quant.tsfm import _hf_cached
        return (True, "ok") if _hf_cached(self.repo) else (False, f"{self.repo} not in local HF cache")

    def score(self, texts: list[str]) -> list[float]:
        if self._pipe is None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            from transformers import pipeline
            self._pipe = pipeline("text-classification", model=self.repo, device=-1, top_k=None, truncation=True)
        res = self._pipe([clean(t, 512) for t in texts])
        out = []
        for r in res:
            d = {x["label"].lower(): x["score"] for x in r}
            out.append(float(d.get("positive", 0.0) - d.get("negative", 0.0)))
        return out


PROVIDERS = [HFClassifier("finbert", "ProsusAI/finbert"),
             HFClassifier("distilroberta", "mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"), Lexicon()]


class TextVeto:
    """veto if sentiment <= veto_at; downsize linearly between veto_at and downsize_at. Never > 1."""

    def __init__(self, veto_at: float = -0.6, downsize_at: float = -0.2, timeout_s: float = 10.0, prefer: str | None = None):
        self.veto_at, self.downsize_at, self.timeout_s = veto_at, downsize_at, timeout_s
        cands = [p for p in PROVIDERS if (prefer is None or p.name == prefer)] or PROVIDERS
        self.provider = next((p for p in cands if p.available()[0]), Lexicon())
        self._pool = cf.ThreadPoolExecutor(max_workers=1)

    def factors(self, texts: list[str]) -> tuple[list[float], list[float], str]:
        """Returns (size factors in [0,1], sentiments, provider name). On timeout/error: factor 1 (no opinion)."""
        if not texts:
            return [], [], self.provider.name
        try:
            s = self._pool.submit(self.provider.score, texts).result(timeout=self.timeout_s)
        except Exception:  # noqa: BLE001 - abstain = no veto, the deterministic risk engine still applies
            return [1.0] * len(texts), [0.0] * len(texts), self.provider.name + ":abstain"
        f = [0.0 if x <= self.veto_at else 1.0 if x >= self.downsize_at else (x - self.veto_at) / (self.downsize_at - self.veto_at) for x in s]
        return [min(1.0, max(0.0, v)) for v in f], s, self.provider.name


def text_card(provider: str) -> ModelCard:
    return ModelCard(
        name=f"News sentiment veto ({provider})", kind="text_veto",
        purpose="Veto or downsize BUYs on strongly negative recent news for the symbol.",
        intended_use="Advisory veto/downsize stage in the paper pipeline and recipe search.",
        out_of_scope="Generating trades, increasing size, reacting to instructions inside headlines.",
        data="Headlines from local caches / disabled news feeds (untrusted text). Pretraining per upstream model card.",
        features=["headline text (sanitised, truncated to 512 chars)"],
        limitations=["Headline sentiment is noisy and often already priced in", "English only", "Lexicon fallback is crude"],
        risks=["Prompt/text injection: mitigated (classifier, not an instruction follower; output is a number)", "Label drift as language shifts"],
        extra={"timeout_s": 10, "on_timeout": "abstain (no veto)"})
