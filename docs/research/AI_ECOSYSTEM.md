# AI ecosystem evidence review

Checked 2026-10-19 using official documentation, repositories and publisher model
cards. This is a technical integration review, not an accuracy ranking or a claim
that all candidates are installed. No paid inference, training, account creation,
or model download was performed. Account-specific quotas and commercial contracts
were not inspected. Prices are a dated snapshot, not configuration defaults.
External market-data/MCP candidates and their separate data-rights gates are
reviewed in [MCP_DATA_INTEGRATION.md](MCP_DATA_INTEGRATION.md).

## Inference and training are separate products

Legend: **Y** documented; **C** conditional on model, serving stack, region or
contract; **N** not offered by that component; **U** not verified. A local tensor
batch is not a hosted asynchronous Batch API. Token streaming is not an online
learning algorithm. Structured numeric output is not LLM JSON-schema generation.

| Product or component | Hosted inference | Fine-tuning | Custom training | Batch inference | Streaming output | Structured outputs | Tool calling |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gemini Developer API | Y | N currently | N | C | Y text streaming; Live is a separate model | C | C |
| xAI Grok API | Y | U | U | C; Grok 4.7 says N | Y | C | C |
| Vertex AI / current Google Cloud ML platform | Y | C | Y | Y | C serving/model | C | C |
| HF Inference Providers | Y | N on inference interface | N | C backend | C | C | C |
| HF dedicated Endpoints + separate Jobs | Y endpoints | Y jobs/model-dependent | Y jobs | Y jobs/custom workload | C engine | C engine/model | C engine/model |
| Chronos-2 weights | Via deployment | Y library | Via training code | Local batches; hosted via deployment | N native token stream | Numeric quantiles | N |
| TimesFM family | Via Cloud or deployment | C version/library/license | Via custom code | Y local/Cloud pathways | N native token stream | Numeric forecasts | N |
| Moirai 2.0 weights | Requires hosting | C Uni2TS recipe/version | Via custom code | Local batches | N native token stream | Numeric quantiles | N |
| IBM Granite TTM | C watsonx/import | Y | Via custom code | C serving stack | U | Numeric forecasts | N |
| Nixtla TimeGPT | Y | Y | U general pretraining | C multi-series/async jobs | U | Numeric forecasts/intervals | N native |
| PyTorch | Requires hosting | Y custom code | Y | Local tensors | Application-defined | Application-defined | Application-defined |
| LightGBM / XGBoost | Requires hosting | Continue/retrain trees, not LLM tuning | Y | Local arrays | Application-defined | Numeric/class outputs | N native |
| SageMaker AI / Azure ML | Y | C model | Y | Y | C endpoint/container | C model/container | C model/container |
| RavenPack Edge / Bigdata API | Hosted financial analytics/retrieval | U | U | C data products | U | Structured analytics | Not an execution interface |

Sources for the capability rows: [Gemini model capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
[Gemini tuning status](https://ai.google.dev/gemini-api/docs/model-tuning),
[xAI model details](https://docs.x.ai/developers/models/grok-4.7),
[xAI API documentation](https://docs.x.ai/developers/models),
[Vertex custom training](https://docs.cloud.google.com/vertex-ai/docs/training/overview),
[Vertex tuning](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/tune-models),
[HF inference routing](https://huggingface.co/docs/inference-providers/index),
[HF Endpoints](https://huggingface.co/docs/inference-endpoints/en/index),
[HF Jobs](https://huggingface.co/docs/hub/en/jobs),
[Chronos repository](https://github.com/amazon-science/chronos-forecasting),
[TimesFM repository](https://github.com/google-research/timesfm),
[Moirai model card](https://huggingface.co/Salesforce/moirai-2.0-R-small),
[IBM managed TTM](https://www.ibm.com/new/announcements/custom-foundation-models-import-support-for-granite-time-series-models),
[TimeGPT tuning](https://www.nixtla.io/docs/forecasting/fine-tuning/steps),
[PyTorch](https://github.com/pytorch/pytorch),
[LightGBM](https://lightgbm.readthedocs.io/en/stable/),
[XGBoost](https://xgboost.readthedocs.io/en/stable/),
[SageMaker training](https://docs.aws.amazon.com/sagemaker/latest/dg/how-it-works-training.html),
[SageMaker inference](https://docs.aws.amazon.com/sagemaker/latest/dg/deploy-model-get-started.html),
[Azure ML](https://learn.microsoft.com/en-us/azure/machine-learning/concept-azure-machine-learning-v2?view=azureml-api-2),
[RavenPack Edge](https://www.ravenpack.com/products/edge).

## Operations, privacy and commercial review

| Component | GPU training | Deployment / versioning | Privacy control | Commercial position |
| --- | --- | --- | --- | --- |
| Gemini API | No customer GPU job | Vendor endpoint; stable/preview IDs, not customer registry | Standard paid data-use terms; contributor tier differs | Paid commercial service under API terms; no weights ownership |
| xAI API | Not verified | Vendor endpoints and model aliases/releases | Default API retention, ZDR and regional options | Commercial API under vendor terms; account eligibility still required |
| Vertex AI | Yes custom jobs | Managed endpoints and Model Registry | IAM, regional controls, caching/retention configuration | Service terms plus each model license |
| HF | Jobs yes | Endpoints; Hub commit revisions | Private repos, protected/private endpoints | Per-service terms AND individual model/data licenses |
| Chronos-2 | Training code supports accelerators | Pin artifact revision/hash; self-host or SageMaker | Local control or hosting controls | Model card says Apache-2.0; archive exact artifact/license evidence before adoption |
| TimesFM 3.0 | Research code; rights restricted | Local weights or authorized Cloud service | Deployment-dependent | Downloaded weights non-commercial/non-production; authorized Cloud route differs |
| Moirai 2.0 | Research code | Pin checkpoint | Local/hosting controls | CC-BY-NC-4.0; excluded from ATLAS commercial use |
| IBM Granite TTM | Fine-tuning workload | Local or watsonx custom import | Hosting-dependent | Enterprise TTM checkpoints Apache-2.0; distinguish research variants |
| TimeGPT | Vendor-managed tuning; no verified GPU-job API | Vendor model versions | Contract review required | Subscription service; exact terms and retention pending |
| PyTorch / LightGBM / XGBoost | Yes, subject to backend/build | Save artifacts; external serving and registry | Local by default | Framework license is separate from training-data and checkpoint rights |
| SageMaker / Azure ML | Yes | Jobs, endpoints, registries and versions | IAM/identity, private networking, region/storage controls | Cloud terms, capacity quotas, model/data licenses |
| RavenPack / Bigdata | Not verified | Vendor data/API releases | Contract/data entitlement controls | Licensed analytics; redistribution/training rights need explicit review |

Privacy evidence: [Google paid versus contributor tier](https://ai.google.dev/gemini-api/docs/pricing),
[Google Cloud data governance](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance),
[xAI API privacy](https://docs.x.ai/developers/faq/security),
[HF endpoint security](https://huggingface.co/docs/inference-endpoints/en/security),
[SageMaker network isolation](https://docs.aws.amazon.com/sagemaker/latest/dg/mkt-algo-model-internet-free.html).
No-training use is not the same as zero retention. xAI documents 30-day default
API retention and says ZDR disables features including Batch and Collections.
ATLAS must record the actual account mode, not infer it from provider branding.

Registry evidence: [Vertex Model Registry](https://docs.cloud.google.com/vertex-ai/docs/model-registry/introduction),
[SageMaker Model Registry](https://docs.aws.amazon.com/en_en/sagemaker/latest/dg/model-registry.html),
[MLflow registry](https://mlflow.org/docs/latest/ml/model-registry/).
MLflow is a portable tracking/registry candidate, not an inference or GPU service.
No MLflow server is installed in this increment.

## Verified identifiers, prices and limits

USD per million tokens, standard uncached text input/output, checked 2026-10-19.
These exclude tools, storage, tax, training, deployment and other modalities.

| Model ID | Input / output | Effective condition | Limits |
| --- | --- | --- | --- |
| `gemini-3.8-flash` | $0.75 / $3.75 | Through 2026-12-31; page lists $1.50 / $7.50 from 2027-01-01 | Actual project quota must be read in AI Studio |
| `gemini-4-argon` | $2 / $10 | Through 2026-11-30; page lists $4 / $20 from 2026-12-01 | Actual project quota must be read in AI Studio |
| `grok-4.7` | $2 / $6 | Listed base pricing; page flags different pricing above 200K context | Model page lists 150 requests/sec and 50M tokens/min for displayed us-east-1; not a guarantee for this account |

Sources: [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Gemini limits](https://ai.google.dev/gemini-api/docs/rate-limits),
[Grok 4.7 details](https://docs.x.ai/developers/models/grok-4.7),
[xAI quota handling](https://docs.x.ai/developers/rate-limits).
The runtime's default local request budget is an ATLAS limit, not a vendor quota.
Unknown prices and quotas remain null/unconfigured; they are never treated as free.

Other verified candidate identifiers: `gemini-embedding-001` and
`gemini-embedding-2-preview` ([Google catalog](https://ai.google.dev/gemini-api/docs/models));
`amazon/chronos-2` ([publisher card](https://huggingface.co/amazon/chronos-2));
`google/timesfm-3.0-pytorch` ([publisher card](https://huggingface.co/google/timesfm-3.0-pytorch));
`Salesforce/moirai-2.0-R-small` ([publisher card](https://huggingface.co/Salesforce/moirai-2.0-R-small));
`ibm-granite/granite-timeseries-ttm-r2` ([IBM research publication](https://research.ibm.com/publications/tiny-time-mixers-ttms-fast-pre-trained-models-for-enhanced-zerofew-shot-forecasting-of-multivariate-time-series--1)).
No general cloud GPU price or numeric quota is asserted: those require region,
instance, reservation, storage, egress and account details. No model is downloaded.

## Candidate roles and adoption order

Gemini remains the preferred narrator behind the research protocol. Grok is an
optional second narrator over its native API; neither produces numeric forecast
probabilities by interpreting its own confidence. Embedding and retrieval are
separate capabilities with source timestamps and collection access controls.

Start numeric comparisons with last-value, zero-return and no-trade baselines.
Then evaluate one tree model on a frozen point-in-time dataset; consider PyTorch
only for a measured gap. Chronos-2 and enterprise Granite TTM are candidates,
not validated winners. TimesFM through authorized Cloud services is a separate
candidate from restricted downloaded weights. Moirai 2.0 stays out of commercial
use. Model-specific license evidence remains mandatory.

RavenPack Edge supplies finance-specific NLP features and point-in-time analytics;
[Bigdata API](https://docs.bigdata.com/) supplies financial research/retrieval.
Neither establishes a public customer GPU training API or a profitable strategy.
[FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) is an additional financial
ML research framework, not a managed provider or proof of transferable accuracy;
base-model, data and adapter licenses need separate review.

For managed jobs, compare Vertex, SageMaker, HF Jobs and Azure ML using the same
artifact/dataset manifest. Selection requires a small measured job, privacy review,
verified region/quota and spend ceiling. No platform is an irreversible dependency.

Bloomberg BQuant Enterprise is another finance-focused candidate: its official
page documents managed dedicated infrastructure, scheduled jobs, integration of
customer data, and scalable compute including GPUs. It is a financial research
workspace, not evidence of an unrestricted public model-training API. Fine-tuning,
streaming, hosted prediction endpoints, tool calling, exact prices and quotas were
not verified here. Data rights and commercial access require the contracted
product entitlements. [Bloomberg BQuant](https://professional.bloomberg.com/products/bloomberg-terminal/research/bquant/).
