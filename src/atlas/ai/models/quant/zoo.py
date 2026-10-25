"""Model kind -> class (for integrity-checked registry loads)."""
from atlas.ai.models.quant.model import TradeFilterModel
from atlas.ai.models.quant.anomaly_ml import AnomalyModel
from atlas.ai.models.quant.costmodel import CostModel
from atlas.ai.models.quant.regime import RegimeModel
from atlas.ai.models.quant.sleeves import StackedScorer
from atlas.ai.models.quant.vol import VolModel
from atlas.ai.models.quant.meta import MetaLabeler
from atlas.ai.models.quant.stack2 import ConformalModel, ExecutionModel, FactorSleeveModel, PortfolioModel

MODEL_CLASSES = {"trade_filter": TradeFilterModel, "scorer_core_etf": StackedScorer,
                 "scorer_active_equity": StackedScorer, "scorer_crypto": StackedScorer, "regime": RegimeModel, "vol": VolModel, "cost": CostModel, "anomaly": AnomalyModel,
                 "meta_label": MetaLabeler, "factor_sleeve": FactorSleeveModel, "portfolio": PortfolioModel,
                 "conformal": ConformalModel, "execution": ExecutionModel}


def register_kind(kind: str, cls) -> None:
    MODEL_CLASSES[kind] = cls


# round-2 strategy challengers (rule-based; artefact = digest-checked parameters)
from atlas.strategies.sleeve_strategies.harness import StratModel  # noqa: E402

for _k in ("strat_vol_managed", "strat_trend_switch"):
    MODEL_CLASSES[_k] = StratModel
