"""Load + validate all config files. Any problem raises ConfigError (fail closed)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from atlas.control.policy.schemas import BrokersCfg, RiskPolicy, ScheduleCfg


class ConfigError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("config invalid (failing closed):\n  - " + "\n  - ".join(errors))


@dataclass(frozen=True)
class LoadedConfig:
    risk: RiskPolicy
    brokers: BrokersCfg
    schedule: ScheduleCfg
    env_example: dict[str, str]
    venues: "object | None" = None
    tax: "object | None" = None
    warnings: list = field(default_factory=list)
    digests: dict[str, str] = field(default_factory=dict)


def _read_yaml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ConfigError([f"{path.name}: top level must be a mapping"])
    return data, hashlib.sha256(raw).hexdigest()


def parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip().strip('"')
        out[k.strip()] = v
    return out


def _apply_profile(p):
    from atlas.risk.autonomy import apply_limit_profile
    return apply_limit_profile(p)


def _env_example(d: Path) -> Path:
    """The single env template is the repo-root .env.example; a config-dir copy (tests) wins if it defines variables."""
    local = d / ".env.example"
    if local.exists() and parse_env_file(local):
        return local
    for up in (d, *d.parents):
        if (up / ".env.example").exists() and up != d and (up / "pyproject.toml").exists():
            return up / ".env.example"
    return local


def load_all(config_dir: str | Path, env_file: str | Path | None = None, verify_signature: bool = True) -> LoadedConfig:
    from atlas.control.policy.validate import cross_validate  # local import to avoid cycle

    d = Path(config_dir)
    errors: list[str] = []
    parsed: dict[str, Any] = {}
    digests: dict[str, str] = {}
    for name, model in (("risk_policy.yaml", RiskPolicy), ("brokers.yaml", BrokersCfg), ("schedule.yaml", ScheduleCfg)):
        p = d / name
        if not p.exists():
            errors.append(f"{name}: missing")
            continue
        try:
            data, digests[name] = _read_yaml(p)
            parsed[name] = model.model_validate(data)
        except ConfigError as e:
            errors.extend(e.errors)
        except (ValidationError, yaml.YAMLError) as e:
            errors.append(f"{name}: {e}")
    if errors:
        raise ConfigError(errors)
    env_path = Path(env_file) if env_file else _env_example(d)
    cfg = LoadedConfig(
        risk=parsed["risk_policy.yaml"],
        brokers=parsed["brokers.yaml"],
        schedule=parsed["schedule.yaml"],
        env_example=parse_env_file(env_path),
        digests=digests,
    )
    from atlas.control.policy.venues import VenuesCfg, validate_venues
    errs = cross_validate(cfg)  # validate the raw policy, then apply the level's (tighter) profile
    object.__setattr__(cfg, "risk", _apply_profile(cfg.risk))
    vp = d / "venues.yaml"
    if not vp.exists():
        errs.append("venues.yaml: missing (eligibility config is required; fail closed)")
    else:
        try:
            vdata, digests["venues.yaml"] = _read_yaml(vp)
            venues = VenuesCfg.model_validate(vdata)
            from atlas.control.policy.venues import load_blocklists
            venues, berrs, bwarns = load_blocklists(venues, d)
            object.__setattr__(cfg, "venues", venues)
            cfg.warnings.extend(bwarns)
            errs += berrs + validate_venues(venues, [k for k, v in cfg.brokers.platforms.items() if v.enabled])
        except (ValidationError, yaml.YAMLError, ConfigError) as e:
            errs.append(f"venues.yaml: {e}")
    from atlas.tax.config import TaxCfg
    tp = d / "tax.yaml"
    try:
        if tp.exists():
            tdata, digests["tax.yaml"] = _read_yaml(tp)
            object.__setattr__(cfg, "tax", TaxCfg.model_validate(tdata))
        else:
            object.__setattr__(cfg, "tax", TaxCfg())
    except (ValidationError, yaml.YAMLError, ConfigError) as e:
        errs.append(f"tax.yaml: {e}")
    if verify_signature:
        from atlas.control.policy.signing import verify_policy
        errs = verify_policy(d) + errs
    if errs:
        raise ConfigError(errs)
    return cfg
