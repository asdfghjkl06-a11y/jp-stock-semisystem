from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yaml
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent

MARGIN_COLUMNS = ["code", "date", "auto_margin_ratio", "auto_long_volume", "auto_short_volume"]
FINANCIAL_COLUMNS = [
    "code", "date", "auto_equity_ratio_pct", "auto_dividend_per_share",
    "auto_sales_growth_pct", "auto_op_growth_pct", "auto_eps_growth_pct",
]


def _num(value: Any) -> float:
    try:
        if value in (None, ""):
            return np.nan
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _code(value: Any) -> str:
    raw = str(value).strip().replace(".0", "")
    return raw[:4] if len(raw) >= 4 else raw.zfill(4)


def _clip_score(value: float, low: float, high: float) -> float:
    if pd.isna(value):
        return 50.0
    if high == low:
        return 50.0
    return float(np.clip((value - low) / (high - low) * 100, 0, 100))


def _inverse_score(value: float, best: float, worst: float) -> float:
    return 100.0 - _clip_score(value, best, worst)


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class JQuantsClient:
    BASE = "https://api.jquants.com/v2"

    def __init__(self, api_key: str, interval: float = 0.15, timeout: int = 30):
        if not api_key:
            raise RuntimeError("JQUANTS_API_KEY が未設定です。.env.example を参考に .env を作成してください。")
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": api_key, "Accept-Encoding": "gzip"})
        self.interval = interval
        self.timeout = timeout

    def get_all(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        query = {k: v for k, v in params.items() if v not in (None, "")}
        while True:
            response = self.session.get(self.BASE + endpoint, params=query, timeout=self.timeout)
            if response.status_code == 429:
                time.sleep(max(2.0, self.interval * 10))
                continue
            response.raise_for_status()
            body = response.json()
            rows.extend(body.get("data", []))
            page = body.get("pagination_key")
            if not page:
                break
            query["pagination_key"] = page
            time.sleep(self.interval)
        time.sleep(self.interval)
        return rows


@dataclass
class DataBundle:
    prices: pd.DataFrame
    auto_margin: pd.DataFrame
    auto_financials: pd.DataFrame


def fetch_jquants(universe: pd.DataFrame, as_of: date, cfg: dict[str, Any]) -> DataBundle:
    load_dotenv(ROOT / ".env")
    dc = cfg["data"]
    client = JQuantsClient(
        os.getenv("JQUANTS_API_KEY", ""),
        interval=float(dc["request_interval_seconds"]),
        timeout=int(dc["timeout_seconds"]),
    )
    start = as_of - timedelta(days=int(dc["lookback_calendar_days"]))
    price_rows: list[dict[str, Any]] = []
    margin_rows: list[dict[str, Any]] = []
    fin_rows: list[dict[str, Any]] = []
    for i, code in enumerate(universe["code"], 1):
        print(f"[{i}/{len(universe)}] {code} を取得中")
        price_rows += client.get_all(
            "/equities/bars/daily", {"code": code, "from": start.isoformat(), "to": as_of.isoformat()}
        )
        margin_rows += client.get_all(
            "/markets/margin-interest", {"code": code, "from": start.isoformat(), "to": as_of.isoformat()}
        )
        fin_rows += client.get_all("/fins/summary", {"code": code})
    return DataBundle(
        prices=_normalize_prices(pd.DataFrame(price_rows)),
        auto_margin=_normalize_margin(pd.DataFrame(margin_rows)),
        auto_financials=_normalize_financials(pd.DataFrame(fin_rows)),
    )


def load_manual_prices() -> pd.DataFrame:
    path = ROOT / "input" / "prices_manual.csv"
    df = pd.read_csv(path, dtype={"code": str})
    required = {"code", "date", "open", "high", "low", "close", "volume", "trading_value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"prices_manual.csv に不足列があります: {sorted(missing)}")
    df["code"] = df["code"].map(_code)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in required - {"code", "date"}:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["code", "date", "close"])


def _normalize_prices(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "volume", "trading_value"])
    out = pd.DataFrame()
    out["code"] = raw["Code"].map(_code)
    out["date"] = pd.to_datetime(raw["Date"], errors="coerce")
    mapping = {"open": "AdjO", "high": "AdjH", "low": "AdjL", "close": "AdjC", "volume": "AdjVo", "trading_value": "Va"}
    for dst, src in mapping.items():
        fallback = {"AdjO": "O", "AdjH": "H", "AdjL": "L", "AdjC": "C", "AdjVo": "Vo"}.get(src)
        values = raw[src] if src in raw else raw.get(fallback, np.nan)
        out[dst] = pd.to_numeric(values, errors="coerce")
    return out.dropna(subset=["date", "code", "close"]).sort_values(["code", "date"])


def _normalize_margin(raw: pd.DataFrame) -> pd.DataFrame:
    cols = MARGIN_COLUMNS
    if raw.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({
        "code": raw["Code"].map(_code),
        "date": pd.to_datetime(raw["Date"], errors="coerce"),
        "auto_long_volume": pd.to_numeric(raw.get("LongVol"), errors="coerce"),
        "auto_short_volume": pd.to_numeric(raw.get("ShrtVol"), errors="coerce"),
    })
    out["auto_margin_ratio"] = out["auto_long_volume"] / out["auto_short_volume"].replace(0, np.nan)
    return out.sort_values("date").groupby("code", as_index=False).tail(1)[cols]


def _normalize_financials(raw: pd.DataFrame) -> pd.DataFrame:
    cols = FINANCIAL_COLUMNS
    if raw.empty:
        return pd.DataFrame(columns=cols)
    raw = raw.copy()
    raw["code"] = raw["Code"].map(_code)
    raw["date"] = pd.to_datetime(raw["DiscDate"], errors="coerce")
    for col in ["EqAR", "FDivAnn", "DivAnn", "Sales", "OP", "EPS"]:
        raw[col] = pd.to_numeric(raw.get(col), errors="coerce")
    raw = raw.sort_values(["code", "date", "DiscNo"] if "DiscNo" in raw else ["code", "date"])
    records = []
    for code, g in raw.groupby("code"):
        g = g.dropna(subset=["date"])
        if g.empty:
            continue
        latest = g.iloc[-1]
        annual = g[g.get("CurPerType", "").astype(str).isin(["FY", "4Q"])] if "CurPerType" in g else g
        annual = annual.tail(2)
        def growth(col: str) -> float:
            s = annual[col].dropna()
            if len(s) < 2 or s.iloc[-2] == 0:
                return np.nan
            return (s.iloc[-1] / abs(s.iloc[-2]) - 1) * 100
        records.append({
            "code": code,
            "date": latest["date"],
            "auto_equity_ratio_pct": _num(latest.get("EqAR")) * 100,
            "auto_dividend_per_share": _num(latest.get("FDivAnn")) if not pd.isna(latest.get("FDivAnn")) else _num(latest.get("DivAnn")),
            "auto_sales_growth_pct": growth("Sales"),
            "auto_op_growth_pct": growth("OP"),
            "auto_eps_growth_pct": growth("EPS"),
        })
    return pd.DataFrame(records, columns=cols)


def make_demo(universe: pd.DataFrame, as_of: date) -> DataBundle:
    rng = np.random.default_rng(20260913)
    days = pd.bdate_range(as_of - timedelta(days=150), as_of)
    price_rows = []
    margin_rows = []
    fin_rows = []
    for idx, row in universe.iterrows():
        base = 450 + idx * 95
        returns = rng.normal(0.0007 + (idx % 5) * 0.0002, 0.014, len(days))
        close = base * np.cumprod(1 + returns)
        volume = rng.integers(600_000, 4_000_000, len(days)).astype(float)
        volume[-1] *= 1 + (idx % 4) * 0.5
        for d, c, v in zip(days, close, volume):
            price_rows.append({"code": row.code, "date": d, "open": c * 0.995, "high": c * 1.015, "low": c * 0.985, "close": c, "volume": v, "trading_value": c * v})
        margin_rows.append({"code": row.code, "date": days[-1], "auto_margin_ratio": 1 + (idx % 8), "auto_long_volume": 2_000_000, "auto_short_volume": 1_000_000})
        fin_rows.append({"code": row.code, "date": days[-1], "auto_equity_ratio_pct": 25 + idx % 8 * 7, "auto_dividend_per_share": 20 + idx % 6 * 5, "auto_sales_growth_pct": -5 + idx % 9 * 3, "auto_op_growth_pct": -8 + idx % 10 * 4, "auto_eps_growth_pct": -10 + idx % 11 * 4})
    return DataBundle(pd.DataFrame(price_rows), pd.DataFrame(margin_rows), pd.DataFrame(fin_rows))


def latest_manual(filename: str) -> pd.DataFrame:
    path = ROOT / "input" / filename
    df = pd.read_csv(path, dtype={"code": str})
    if df.empty:
        return df
    df["code"] = df["code"].map(_code)
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("date").groupby("code", as_index=False).tail(1)
    return df


def build_features(universe: pd.DataFrame, bundle: DataBundle) -> pd.DataFrame:
    rows = []
    for code, g in bundle.prices.groupby("code"):
        g = g.sort_values("date").copy()
        if len(g) < 80:
            continue
        for n in [5, 20, 25, 75]:
            g[f"ma{n}"] = g["close"].rolling(n).mean()
        latest = g.iloc[-1]
        ma5_prev = g["ma5"].iloc[-6]
        ma25_prev = g["ma25"].iloc[-6]
        rows.append({
            "code": code,
            "price_date": latest["date"],
            "close": latest["close"],
            "volume": latest["volume"],
            "trading_value": latest["trading_value"],
            "ma5": latest["ma5"], "ma25": latest["ma25"], "ma75": latest["ma75"],
            "ma5_slope_pct": (latest["ma5"] / ma5_prev - 1) * 100,
            "ma25_slope_pct": (latest["ma25"] / ma25_prev - 1) * 100,
            "deviation_5ma_pct": (latest["close"] / latest["ma5"] - 1) * 100,
            "return_5d_pct": (latest["close"] / g["close"].iloc[-6] - 1) * 100,
            "return_20d_pct": (latest["close"] / g["close"].iloc[-21] - 1) * 100,
            "avg_volume20": g["volume"].iloc[-21:-1].mean(),
            "rvol": latest["volume"] / g["volume"].iloc[-21:-1].mean(),
            "near_20d_high_pct": (latest["close"] / g["high"].tail(20).max()) * 100,
        })
    out = universe.merge(pd.DataFrame(rows), on="code", how="left")
    out = out.merge(bundle.auto_margin, on="code", how="left", suffixes=("", "_margin"))
    out = out.merge(bundle.auto_financials, on="code", how="left", suffixes=("", "_fin"))
    return out


def merge_manual(features: pd.DataFrame) -> pd.DataFrame:
    supply = latest_manual("supply_demand.csv")
    fundamentals = latest_manual("fundamentals.csv")
    catalysts = latest_manual("catalysts.csv")
    out = features.merge(supply.drop(columns=["date", "note"], errors="ignore"), on="code", how="left")
    out = out.merge(fundamentals.drop(columns=["date", "note"], errors="ignore"), on="code", how="left")
    out = out.merge(catalysts.drop(columns=["date"], errors="ignore"), on="code", how="left")
    # 手入力を優先し、なければJ-Quants由来を補完する。
    def numeric_column(name: str) -> pd.Series:
        values = out[name] if name in out else pd.Series(np.nan, index=out.index)
        return pd.to_numeric(values, errors="coerce")

    out["margin_ratio"] = numeric_column("margin_ratio").fillna(numeric_column("auto_margin_ratio"))
    out["equity_ratio_pct"] = numeric_column("equity_ratio_pct").fillna(numeric_column("auto_equity_ratio_pct"))
    for manual, auto in [("sales_growth_pct", "auto_sales_growth_pct"), ("operating_profit_growth_pct", "auto_op_growth_pct"), ("eps_growth_pct", "auto_eps_growth_pct")]:
        out[manual] = numeric_column(manual).fillna(numeric_column(auto))
    dividend = numeric_column("dividend_yield_pct")
    derived_yield = numeric_column("auto_dividend_per_share") / numeric_column("close") * 100
    out["dividend_yield_pct"] = dividend.fillna(derived_yield)
    for col in ["lending_ratio", "turnover_days", "material_score"]:
        out[col] = numeric_column(col)
    return out


def score(features: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    df = features.copy()
    po = np.select(
        [(df.ma5 > df.ma25) & (df.ma25 > df.ma75), (df.ma5 > df.ma25), (df.ma25 > df.ma75)],
        [100, 72, 62], default=30,
    )
    above = np.where(df.close > df.ma5, 100, np.where(df.close > df.ma25, 55, 15))
    dev_quality = 100 - np.clip(np.abs(df.deviation_5ma_pct - 1.5) * 11, 0, 100)
    df["technical_score"] = (
        above * 0.22 + po * 0.23 + df.ma5_slope_pct.map(lambda x: _clip_score(x, -3, 3)) * 0.20
        + df.ma25_slope_pct.map(lambda x: _clip_score(x, -5, 5)) * 0.12
        + df.return_20d_pct.map(lambda x: _clip_score(x, -15, 20)) * 0.08
        + df.near_20d_high_pct.map(lambda x: _clip_score(x, 82, 100)) * 0.07
        + dev_quality * 0.08
    )
    df["supply_score"] = (
        df.margin_ratio.map(lambda x: _inverse_score(x, 0.5, 7)) * 0.38
        + df.lending_ratio.map(lambda x: _inverse_score(x, 0.5, 7)) * 0.34
        + df.turnover_days.map(lambda x: _inverse_score(x, 0.5, 7)) * 0.28
    )
    df["rvol_score"] = df.rvol.map(lambda x: _clip_score(x, 0.7, 3.0)) * 0.72 + df.return_5d_pct.map(lambda x: _clip_score(x, -5, 12)) * 0.28
    df["financial_score"] = (
        df.equity_ratio_pct.map(lambda x: _clip_score(x, 15, 70)) * 0.28
        + df.dividend_yield_pct.map(lambda x: _clip_score(x, 0, 5)) * 0.18
        + df.sales_growth_pct.map(lambda x: _clip_score(x, -10, 20)) * 0.16
        + df.operating_profit_growth_pct.map(lambda x: _clip_score(x, -15, 30)) * 0.20
        + df.eps_growth_pct.map(lambda x: _clip_score(x, -20, 35)) * 0.18
    )
    df["catalyst_score"] = df.material_score.fillna(50).clip(0, 100)
    df["data_completeness_pct"] = df[["margin_ratio", "lending_ratio", "turnover_days", "equity_ratio_pct", "dividend_yield_pct", "sales_growth_pct", "operating_profit_growth_pct", "eps_growth_pct", "material_score"]].notna().mean(axis=1) * 100
    f = cfg["filter"]
    liquidity = (df.volume >= f["min_volume"]) | (df.trading_value >= f["min_trading_value_yen"])
    supply_ok = (df.margin_ratio <= f["max_margin_ratio"]) & (df.lending_ratio <= f["max_lending_ratio"]) & (df.turnover_days <= f["max_turnover_days"])
    if not f["strict_supply_data"]:
        supply_ok = supply_ok | df[["margin_ratio", "lending_ratio", "turnover_days"]].isna().any(axis=1)
    df["filter_pass"] = liquidity & supply_ok
    c = cfg["chart"]
    df["chart_judgement"] = np.select(
        [df.deviation_5ma_pct >= c["chase_deviation_pct"], (df.close > df.ma5) & (df.ma5_slope_pct > 0), df.deviation_5ma_pct < c["negative_deviation_pct"]],
        ["押し待ち", "今買える", "見送り/押し待ち"], default="押し待ち"
    )
    for mode, weights in cfg["weights"].items():
        df[f"score_{mode}"] = sum(df[f"{k}_score"] * float(w) for k, w in weights.items())
    return df


def _evaluation(row: pd.Series) -> str:
    strengths = []
    if row.technical_score >= 70: strengths.append("チャート良好")
    if row.supply_score >= 70: strengths.append("需給軽い")
    if row.rvol >= 1.5: strengths.append(f"RVOL {row.rvol:.1f}倍")
    if row.financial_score >= 70: strengths.append("財務良好")
    if row.catalyst_score >= 70: strengths.append("材料強い")
    return "、".join(strengths[:3]) or "総合バランス型"


def export_results(df: pd.DataFrame, cfg: dict[str, Any], as_of: date) -> Path:
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    eligible = df[df.filter_pass].copy()
    eligible["評価"] = eligible.apply(_evaluation, axis=1)
    mode_names = {"normal": "通常型", "surge": "噴き上げ型", "early_flow": "初動需給型"}
    rankings: dict[str, pd.DataFrame] = {}
    for mode, jp_name in mode_names.items():
        top = eligible.sort_values(f"score_{mode}", ascending=False).head(int(cfg["output"]["top_n"])).copy()
        top.insert(0, "順位", range(1, len(top) + 1))
        top["総合点"] = top[f"score_{mode}"].round(1)
        rankings[jp_name] = top[["順位", "code", "name", "chart_judgement", "総合点", "評価", "deviation_5ma_pct", "rvol", "data_completeness_pct"]].rename(columns={"code": "コード", "name": "銘柄", "chart_judgement": "チャート判定", "deviation_5ma_pct": "5MA乖離率%", "rvol": "RVOL", "data_completeness_pct": "データ充足率%"})
    xlsx = out_dir / f"screening_{as_of.isoformat()}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        for name, table in rankings.items():
            table.to_excel(writer, sheet_name=name, index=False)
        df.to_excel(writer, sheet_name="全銘柄・監査用", index=False)
        failed = df[~df.filter_pass][["code", "name", "volume", "trading_value", "margin_ratio", "lending_ratio", "turnover_days"]]
        failed.to_excel(writer, sheet_name="一次フィルター除外", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                width = min(max(len(str(cell.value or "")) for cell in col) + 2, 36)
                ws.column_dimensions[col[0].column_letter].width = width
    report = out_dir / f"report_{as_of.isoformat()}.md"
    lines = [f"# 日本株スクリーニング結果（{as_of.isoformat()}）", "", f"一次フィルター通過: {len(eligible)} / {len(df)}銘柄", ""]
    for name, table in rankings.items():
        lines += [f"## {name} TOP{len(table)}", "", table.to_markdown(index=False), ""]
    if rankings["通常型"].empty:
        lines += ["## 注意", "", "一次フィルター通過銘柄がありません。特に supply_demand.csv の貸借倍率・回転日数を確認してください。", ""]
    else:
        lines += ["## ChatGPTへの依頼", "", "添付Excelの上位銘柄について、需給・テクニカル・材料・財務の4点から、強み・リスク・5MA乖離状態を簡潔に考察してください。材料は最新の適時開示・決算を一次情報で確認し、事実と推測を分けてください。", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    df.to_csv(out_dir / f"candidates_{as_of.isoformat()}.csv", index=False, encoding="utf-8-sig")
    return xlsx


def run(as_of_text: str | None = None, demo: bool = False) -> Path:
    cfg = load_config(ROOT / "config.yaml")
    as_of = datetime.strptime(as_of_text, "%Y-%m-%d").date() if as_of_text else date.today()
    universe = pd.read_csv(ROOT / "input" / "universe.csv", dtype={"code": str})
    universe["code"] = universe["code"].map(_code)
    if demo or cfg["data"]["source"] == "demo":
        bundle = make_demo(universe, as_of)
    elif cfg["data"]["source"] == "manual_csv":
        bundle = DataBundle(
            load_manual_prices(),
            pd.DataFrame(columns=MARGIN_COLUMNS),
            pd.DataFrame(columns=FINANCIAL_COLUMNS),
        )
    else:
        bundle = fetch_jquants(universe, as_of, cfg)
    features = build_features(universe, bundle)
    merged = merge_manual(features)
    if demo or cfg["data"]["source"] == "demo":
        # デモだけは手入力ファイルが空でも一次フィルターまで確認できるようにする。
        idx = pd.Series(np.arange(len(merged)), index=merged.index)
        merged["margin_ratio"] = merged["margin_ratio"].fillna(1.0 + idx % 8)
        merged["lending_ratio"] = merged["lending_ratio"].fillna(0.8 + idx % 7)
        merged["turnover_days"] = merged["turnover_days"].fillna(1.2 + idx % 7)
        merged["material_score"] = merged["material_score"].fillna(40 + idx % 7 * 8)
    scored = score(merged, cfg)
    return export_results(scored, cfg, as_of)
