from __future__ import annotations

from pathlib import Path

from atlas.whale_saas_az import (
    build_master_roadmap_state,
    compute_b2b_saas_pricing_quote,
    compute_challenger_model_benchmark,
    export_master_roadmap_csvs,
)


def test_challenger_model_benchmark_and_b2b_pricing() -> None:
    bench = compute_challenger_model_benchmark(track="both")
    assert bench["execution_permission"] == "none"
    assert bench["auto_promoted"] is False
    assert len(bench["benchmarks"]) == 6
    cb_ids = [b["benchmark_id"] for b in bench["benchmarks"]]
    assert cb_ids == ["CB-01", "CB-02", "CB-03", "CB-04", "CB-05", "CB-06"]
    for item in bench["benchmarks"]:
        assert item["deflated_sharpe_dsr"] >= 0.95
        assert item["ece_calibration"] <= 0.035

    quote = compute_b2b_saas_pricing_quote(
        active_trader_seats=250,
        monthly_hedged_volume_usd=45_000_000.0,
        monthly_eval_fees_usd=120_000.0,
        backtest_compute_hours=180.0,
    )
    assert quote["execution_permission"] == "none"
    assert quote["non_custodial_software_only"] is True
    assert quote["customer_funds_touched"] is False
    assert quote["ledger_target"] == "software_subscription"
    assert quote["total_monthly_mrr_usd"] > 10_000.0

    state = build_master_roadmap_state("SPY")
    assert len(state["roadmap_az"]) == 26
    assert len(state["b2b_saas_verticals"]) == 12
    assert "challenger_benchmarks" in state
    assert "b2b_pricing_quote" in state


def test_export_master_roadmap_csvs(tmp_path: Path) -> None:
    exported = export_master_roadmap_csvs(output_dir=tmp_path)
    assert "tab1_platform_roadmap_az.csv" in exported
    assert "tab1b_challenger_model_benchmarks.csv" in exported
    assert "tab4_prop_b2b_saas_verticals.csv" in exported
    for csv_file in exported.values():
        assert Path(csv_file).exists()
        assert Path(csv_file).stat().st_size > 100

