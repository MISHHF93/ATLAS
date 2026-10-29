"""Enumerate every model-training feature list from the code and print exact counts. Usage: PYTHONPATH=src python scripts/feature_inventory.py [--json]

Nothing is hard-coded: counts are len() of the tuples the trainers import, so this cannot drift from the code."""
from __future__ import annotations

import json
import sys

from atlas.ai.ml.dataset import FEATURES as META_FEATURES, SETUP_FEATURES, SIGNED
from atlas.ai.ml.directional import features as DF, layers25 as L
from atlas.ai.ml.features import BASE_BAR_FEATURES, BAR_FEATURES
from atlas.ai.ml.vwap_features import VWAP_FEATURES
from atlas.features.representations.features import REP_FEATURES
from atlas.research import vertical_slice_features as VS


def inventory() -> dict:
    refs = ("SPY",)                                    # one reference instrument, as in a typical directional run
    v2, v3 = DF.v2_feature_names(refs), DF.feature_names(refs)
    groups_v2 = {"bar_base": len(BASE_BAR_FEATURES), "vwap": len(VWAP_FEATURES), "har_volatility": len(DF.HAR_FEATURES), "multi_horizon": len(DF.MTF_FEATURES),
                 "regime": len(DF.REGIME_FEATURES), "cross_asset_one_ref": len(v2) - len(BAR_FEATURES) - len(DF.HAR_FEATURES) - len(DF.MTF_FEATURES) - len(DF.REGIME_FEATURES)}
    return {
        "meta_stack": {"total": len(META_FEATURES), "bar": len(BASE_BAR_FEATURES), "vwap": len(VWAP_FEATURES), "setup": len(SETUP_FEATURES), "setup_x_dir": len(SIGNED),
                       "note": "registered meta-label models store their own list; unchanged by evo-14"},
        "directional_before": {"total": len(v2), "groups": groups_v2},
        "directional_after": {"total": len(v3), "added": len(L.LAYER_FEATURE_NAMES), "layer_groups": {k: len(v) for k, v in L.LAYER_FEATURES.items()}},
        "research_vertical_slice": {"total": len(VS.RESEARCH_FEATURE_NAMES), "bar": len(VS.FEATURE_NAMES), "session": len(VS.SESSION_FEATURE_NAMES), "cross_asset": len(VS.CROSS_ASSET_FEATURE_NAMES)},
        "representation_genome_per_bar_type": len(REP_FEATURES),
        "unique_and_disjoint": {"v3_unique": len(set(v3)) == len(v3), "layer_names_disjoint_from_v2": set(L.LAYER_FEATURE_NAMES).isdisjoint(v2)},
    }


if __name__ == "__main__":
    inv = inventory()
    print(json.dumps(inv, indent=1) if "--json" in sys.argv else json.dumps(inv))
