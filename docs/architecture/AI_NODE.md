# AI node

All AI/ML/LLM work in ATLAS is one node: the `atlas.ai` package. Consumers (UI, scripts, other packages) go through its facade.

```mermaid
flowchart LR
  UI[Frontend pages] -->|/api/ai/* and legacy /api/ml, /api/research, /api/intel, /api/advanced-ml, /api/agent| MW[AINodeMiddleware: one advisory guard]
  MW --> R[atlas.ai.http router]
  R --> N[atlas.ai.node.NODE]
  Scripts[scripts/* and CLIs] --> N
  N --> REG[REGISTRY: 14 components]
  N --> AUD[audit trail var/ai/audit.jsonl]
  REG --> ML[atlas.ml: dataset, features, CV, train, registry, evolution, selector, drift, retrieval]
  REG --> MOD[atlas.ai.models: serving, challengers, continuous learning, chart reader, calibration]
  REG --> INT[atlas.intel + atlas.ai.assistant + LLM providers]
  REG --> EXT[atlas.ext: dossier, personas, debate pipeline]
  MW -->|execution_permission = none| OUT[advisory output]
  OUT --> CP[atlas.control: deterministic control plane, sole authorizer]
```

- Facade: `atlas.ai.node.NODE` (`components()`, `status()`, `guard()`), `enforce_advisory()`, `audit()`.
- Statuses: `ok | degraded | unavailable | refused`.
- API: `GET /api/ai`, `/api/ai/status`, `/api/ai/components`, `/api/ai/components/{name}`, `/api/ai/audit`; `/api/ai/<ns>/...` aliases `/api/<ns>/...` (both guarded).
- `execution_permission` is forced to `"none"` in one place (the middleware → `enforce_advisory`), any override is audited. Nothing in the node can authorize an order; only `atlas.control` can.
