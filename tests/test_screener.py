from datetime import date
import math

import pandas as pd

from screener import (
    FINANCIAL_COLUMNS,
    MARGIN_COLUMNS,
    DataBundle,
    build_features,
    load_config,
    make_demo,
    merge_manual,
    score,
)


def test_demo_scores_and_filters():
    cfg = load_config(__import__("pathlib").Path(__file__).parents[1] / "config.yaml")
    universe = pd.DataFrame({"code": ["7203", "8306"], "name": ["A", "B"]})
    bundle = make_demo(universe, date(2026, 9, 11))
    f = build_features(universe, bundle)
    f["margin_ratio"] = [1.0, 8.0]
    f["lending_ratio"] = [1.0, 1.0]
    f["turnover_days"] = [2.0, 2.0]
    f["equity_ratio_pct"] = [50.0, 50.0]
    f["dividend_yield_pct"] = [3.0, 3.0]
    f["sales_growth_pct"] = [5.0, 5.0]
    f["operating_profit_growth_pct"] = [8.0, 8.0]
    f["eps_growth_pct"] = [10.0, 10.0]
    f["material_score"] = [60.0, 60.0]
    f["volume"] = [1_500_000, 1_500_000]
    out = score(f, cfg)
    assert bool(out.loc[0, "filter_pass"])
    assert not bool(out.loc[1, "filter_pass"])
    assert out.filter(like="score_").notna().all().all()


def test_config_weights_sum_to_one():
    cfg = load_config(__import__("pathlib").Path(__file__).parents[1] / "config.yaml")
    for weights in cfg["weights"].values():
        assert math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-12)


def test_manual_mode_empty_api_frames_can_merge():
    universe = pd.DataFrame({"code": ["7203"], "name": ["A"]})
    bundle = make_demo(universe, date(2026, 9, 11))
    manual_bundle = DataBundle(
        prices=bundle.prices,
        auto_margin=pd.DataFrame(columns=MARGIN_COLUMNS),
        auto_financials=pd.DataFrame(columns=FINANCIAL_COLUMNS),
    )
    features = build_features(universe, manual_bundle)
    merged = merge_manual(features)
    assert "margin_ratio" in merged
    assert "equity_ratio_pct" in merged
