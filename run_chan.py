"""缠论三买策略回测入口。

用法：
    python3 run_chan.py                    # 默认参数
    python3 run_chan.py --no-timing --hold 10 --tag loose
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

import data
from backtest import Costs
from chan_strategy import ChanBacktester, ChanParams, build_signals

DATA_START = "2014-06-01"
RATIO_KEYS = {"年数", "夏普(rf=2%)", "索提诺", "卡玛比率", "交易笔数"}


def fmt(k: str, v) -> str:
    if isinstance(v, float) and k not in RATIO_KEYS:
        return f"{v:.2%}" if abs(v) < 100 else f"{v:,.0f}"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def load(start: str, end: str, top_n: int):
    cached = os.path.join(data.CACHE_DIR, f"daily_2015-01-01_{end}_{top_n}.parquet")
    if os.path.exists(cached):
        px = pd.read_parquet(cached)
    else:
        uni_path = os.path.join(data.CACHE_DIR, f"universe{top_n}.parquet")
        uni = pd.read_parquet(uni_path) if os.path.exists(uni_path) else data.build_universe(top_n)
        px = data.fetch_daily(uni["code"].tolist(), start=DATA_START, end=end)
    bad = px.loc[px[["open", "high", "low", "close"]].min(axis=1) <= 0, "code"].unique()
    if len(bad):
        px = px[~px["code"].isin(bad)]
    idx = data.fetch_index("sh000300", DATA_START, end)
    return data.to_panel(px), idx, len(px["code"].unique())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--top-n", type=int, default=500)
    ap.add_argument("--hold", type=int, default=8)
    ap.add_argument("--min-gap", type=int, default=3)
    ap.add_argument("--min-leave", type=float, default=0.0)
    ap.add_argument("--stop-loss", type=float, default=0.10)
    ap.add_argument("--trail-stop", type=float, default=0.15)
    ap.add_argument("--no-timing", action="store_true")
    ap.add_argument("--no-zg-break", action="store_true")
    ap.add_argument("--tag", default="chan")
    a = ap.parse_args()

    panel, idx, n_codes = load(a.start, a.end, a.top_n)
    cp = ChanParams(
        hold_num=a.hold,
        min_gap=a.min_gap,
        min_leave=a.min_leave,
        stop_loss=a.stop_loss,
        trail_stop=a.trail_stop,
        timing=not a.no_timing,
        zg_break=not a.no_zg_break,
    )
    print(f"股票池 {n_codes} 只，{a.start} ~ {a.end}")
    sig = build_signals(panel, cp)
    n_sig = sum(int((s["kind"] == "buy3").sum()) for s in sig.values())
    print(f"缠论分解完成：{len(sig)} 只股票有信号，历史三买信号 {n_sig} 个")

    bt = ChanBacktester(panel, idx, cp, Costs())
    eq = bt.run(a.start, a.end, signals=sig)
    bench = idx.set_index("date")["close"] if "date" in idx.columns else idx["close"]
    st = bt.stats(eq, bench)

    print("\n===== 缠论三买策略回测 =====")
    for k, v in st.items():
        print(f"{k:<18}{fmt(k, v)}")

    reasons = pd.Series([t.reason for t in bt.trades if t.side == "sell"]).value_counts()
    print("\n卖出原因分布:")
    print(reasons.to_string())

    eq.to_csv(f"equity_{a.tag}.csv")
    pd.DataFrame([t.__dict__ for t in bt.trades]).to_csv(f"trades_{a.tag}.csv", index=False)
    print(f"\n净值 -> equity_{a.tag}.csv, 成交明细 -> trades_{a.tag}.csv")


if __name__ == "__main__":
    main()
