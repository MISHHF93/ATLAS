# Strategy catalog (registry ids)

| id | family | scope | default | status | definition |
|---|---|---|---|---|---|
| dual_band_breakout | breakout | all | on | implemented (legacy) | dual Bollinger band breakout zones |
| wick_reversal | zone_rejection | all | on | implemented (legacy) | wick reversal zones |
| orb_retest | snapback | needs a session | on | implemented (legacy) | 1h opening range → breakout → retest |
| prior_day_range_reversal | zone_rejection | needs a session | on | implemented (legacy) | 3-candle prior-day range reversal |
| sfp | sfp | all | **off** | implemented | see `sfp.md` |
| gold_snapback | snapback | GC, MGC only | **off** | implemented | opening box accepted (k closes beyond) → retest holds (post-accept retest_success) → continuation. Stop modes: box_opposite, box_mid, two_box_heights, retest_extreme; target 2R |
| gold_orb_breakout | orb | GC, MGC only | **off** | implemented | opening box breakout acceptance; shares event_id with snapback so they dedupe |
| four_box | box | – | off | reserved | not implemented; cannot be enabled |

Toggles: `GET /api/quant/strategies`, `POST /api/quant/strategies/{id} {"enabled": bool}`. They are persisted in `$ATLAS_STRATEGY_REGISTRY` (default `var/strategy_registry.json`, never committed). A toggle never grants execution permission.
