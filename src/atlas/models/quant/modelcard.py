"""Model cards (ISO/IEC 42001-style documentation) stored next to each registered model."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("name", "kind", "purpose", "intended_use", "out_of_scope", "data", "features", "limitations", "risks", "human_oversight")


@dataclass
class ModelCard:
    name: str
    kind: str
    purpose: str
    intended_use: str
    out_of_scope: str
    data: str
    features: list[str]
    limitations: list[str]
    risks: list[str]
    human_oversight: str = ("Paper only. Promotion needs shadow gates (>=4 weeks) and owner sign-off at autonomy L>=3; "
                            "drift auto-demotes; the deterministic risk engine has the final say on every order.")
    owner: str = "masharai"
    authority: str = "advisory: filter/scale-down only; cannot create orders or raise limits"
    validation: str = "purged walk-forward CV (embargoed), out-of-sample metrics"
    extra: dict = field(default_factory=dict)

    def validate(self) -> None:
        missing = [k for k in REQUIRED if not getattr(self, k)]
        if missing:
            raise ValueError(f"model card incomplete: {missing}")

    def write(self, d: Path, model_id: str, metrics: dict, data_hash: str = "") -> None:
        self.validate()
        body = asdict(self) | {"model_id": model_id, "metrics": metrics, "data_hash": data_hash,
                               "generated": datetime.now(timezone.utc).isoformat()}
        (d / "model_card.json").write_text(json.dumps(body, indent=1, default=str))
        top = {k: v for k, v in metrics.items() if isinstance(v, (int, float, str))}
        md = [f"# Model card: {self.name} ({model_id})", "", f"**Kind:** {self.kind}  ", f"**Owner:** {self.owner}  ",
              f"**Authority:** {self.authority}", "", "## Purpose", self.purpose, "", "## Intended use", self.intended_use, "",
              "## Out of scope", self.out_of_scope, "", "## Data", self.data, f"(data hash `{data_hash[:16]}`)", "",
              "## Features", ", ".join(self.features), "", "## Validation", self.validation, "", "## Metrics"]
        md += [f"- {k}: {v}" for k, v in top.items()] or ["- see model_card.json"]
        md += ["", "## Limitations"] + [f"- {x}" for x in self.limitations]
        md += ["", "## Risks"] + [f"- {x}" for x in self.risks]
        md += ["", "## Human oversight", self.human_oversight, ""]
        (d / "model_card.md").write_text("\n".join(md))
