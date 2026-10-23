# AI transformers for the paper trading bot: research and decisions (Oct 2026)

Scope: time-series foundation models (TSFMs) and finance text transformers, added as **advisory recipe
components**. They can only rank, veto or shrink. They never create orders or approve anything, and they do not
change policy.

## 1. Time-series foundation models

| Model | Latest (Oct 2026) | Size / CPU? | Licence / notes | Source |
|---|---|---|---|---|
| Chronos-2 | 120M encoder-only; uni-, multivariate and covariates; 8k context | CPU possible but slow; GPU recommended | Apache-2.0; beats Chronos-Bolt in >90% of head-to-heads | https://huggingface.co/amazon/chronos-2 , https://github.com/amazon-science/chronos-forecasting/releases/tag/v2.0.0 , https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting |
| Chronos-Bolt | tiny 9M / mini 21M / small 48M / base 205M; univariate | **tiny runs on our CPU box** (≈8 s including load for 8 series) | Apache-2.0 | https://github.com/amazon-science/chronos-forecasting/ |
| TimesFM | 2.5 (200M, 16k context, XReg covariates, LoRA fine-tuning); 3.0 checkpoint listed | 200M: CPU feasible for small batches | Apache-2.0 | https://github.com/google-research/timesfm/ , https://github.com/google-research/timesfm/tree/master/timesfm-forecasting/examples/finetuning |
| Moirai 2.0 | R-small, decoder-only, top MASE on GIFT-Eval among non-leaking models | small: CPU feasible | Research-only release (check AUP) | https://www.salesforce.com/blog/moirai-2-0/ , https://huggingface.co/Salesforce/moirai-2.0-R-small , https://github.com/SalesforceAIResearch/uni2ts |
| Lag-Llama | small decoder-only probabilistic model (Student-t) | CPU OK | Apache-2.0 | https://github.com/time-series-foundation-models/lag-llama |
| PatchTST / TFT | trained from scratch per fold | CPU OK for small panels | via neuralforecast | https://github.com/Nixtla/neuralforecast |

**What the evidence says about returns (honest):**
- Re(Visiting) TSFMs in Finance (34 years, 94 countries): off-the-shelf zero-shot Chronos and TimesFM post **negative OOS R²**
  on daily excess returns and lose to tree ensembles (CatBoost). Pre-training on financial data closes much of the gap.
  https://arxiv.org/html/2511.18578 (summary: https://tim-frenzel.com/insights/re-visiting-time-series-foundation-models-in)
- Pretrained TSFMs for return forecasting (2026): they win the rankings, but gains over a random walk are "small and sparse".
  Diebold–Mariano rejects the null in only 2 cases. https://arxiv.org/html/2606.27100
- Realized volatility (2026): 8 of 9 zero-shot TSFMs do **not** beat a well-specified Log-HAR on average.
  https://arxiv.org/html/2607.05291v1. Decision: **keep HAR/GARCH as the vol model**. A TSFM vol forecast is at most a challenger.
- Finance-native TSFMs (FinCast, Kronos) report better zero-shot numbers on their own benchmarks, which are less comparable.
  https://arxiv.org/html/2508.19609v1

**Decision:** add a `tsfm` model option to the recipe search, using Chronos-Bolt-tiny offline on CPU (verified working in
the box) or the in-fold `patch-linear` fallback (a PatchTST-inspired linear head). LightGBM per-sleeve remains the
default. TimesFM, Moirai, Lag-Llama and PatchTST are wired as providers: when their package or weights are absent they
report "unavailable", and the recipe falls back without failing. Chronos-2 is the next candidate once a GPU is
available or CPU latency proves acceptable.

## 2. Finance text transformers

| Option | Notes | Source |
|---|---|---|
| FinBERT (ProsusAI/finbert) | Fast and cheap; strong on Financial PhraseBank; **brittle under paraphrase** (accuracy 97% → 71% with GPT-4o paraphrases) | https://huggingface.co/ProsusAI/finbert , https://tommijohnsen.substack.com/p/how-to-break-a-financial-sentiment |
| DistilRoBERTa financial news | Small CPU classifier, used as a second opinion | https://huggingface.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis |
| FinGPT v3.x (LoRA on Llama-2 7/13B, ChatGLM2) | Higher weighted F1 than FinBERT on FiQA/TFNS; 6–13B is too heavy for our CPU path | https://github.com/AI4Finance-Foundation/FinGPT/tree/master/fingpt/FinGPT_Sentiment_Analysis_v3 , https://huggingface.co/FinGPT |
| Small open LLMs (Qwen3-8B, Llama3-8B) | Beat FinBERT across 5 datasets even with 5% of training data; need a GPU or a hosted API | https://arxiv.org/html/2512.00946 , https://doi.org/10.61173/gvntfv56 |

**Decision:** `textai.TextVeto` picks the first available provider in this order: FinBERT, then DistilRoBERTa (both run
offline from the local HF cache; verified), then the existing `HttpLLM` provider (disabled unless env is configured),
then a lexicon fallback. The output is a number in [-1, 1]. It is mapped to a size factor in [0, 1]: veto at ≤ -0.6,
downsize down to -0.2, never above 1. On a 10 s timeout the classifier **abstains** (no veto) and the deterministic risk
engine still applies. Headline text is sanitised and truncated. A classifier cannot follow instructions embedded in a
headline, and the test feeds it "IGNORE PREVIOUS INSTRUCTIONS…" to confirm.

## 3. Governance (ISO/IEC 42001-style)
- Model cards: `tsfm.tsfm_card()`, `textai.text_card()` and the recipe challenger card cover intended use, data, limits,
  risks and human oversight.
- Drift: `TSFMComponent.drift()` tracks recent MAE against reference MAE plus the timeout/error rate. Text drift is covered
  by the existing PSI drift monitor on veto rates. Drift auto-demotes; it never auto-promotes.
- Timeouts: TSFM 20 s, text 10 s. Both fail closed: TSFM abstains (score 0), text abstains (no veto).
- Offline: `HF_HUB_OFFLINE=1`. Nothing downloads at run time. Weights were fetched once into `~/.cache/huggingface` on the box.
