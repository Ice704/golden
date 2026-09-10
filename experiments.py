"""对照实验：逐条验证每个模块（择时、止损、调仓频率、持仓数）是否真的有用。

python3 experiments.py
"""
from __future__ import annotations

import os

import pandas as pd

from backtest import Backtester, Costs
from run_backtest import load
from strategy import Params

HERE = os.path.dirname(os.path.abspath(__file__))
START, END = "2016-01-01", "2026-09-10"

VARIANTS: dict[str, dict] = {
    "基准: 月度+择时+双止损": {},
    "无大盘择时": {"timing": False},
    "无跌破均线离场": {"trail_ma": 0},
    "无止损(仅月度轮动)": {"trail_ma": 0, "stop_loss": 1.0},
    "周度调仓": {"rebalance": "W"},
    "周度+无均线离场": {"rebalance": "W", "trail_ma": 0},
    "持仓5只": {"hold_num": 5},
    "持仓20只": {"hold_num": 20},
    "择时用60日线": {"index_ma": 60},
    "纯动量(不减反转/波动)": {"rev_weight": 0.0, "vol_weight": 0.0},
    "动量窗口60日": {"mom_window": 60},
    "动量窗口250日": {"mom_window": 250},
}


def main() -> None:
    panel, idx = load(START, END, 1200)
    bench = idx.set_index("date")["close"]
    rows = []
    for name, kw in VARIANTS.items():
        params = Params(**kw)
        bt = Backtester(panel, idx, params, Costs())
        eq = bt.run(START, END)
        s = bt.stats(eq, bench)
        rows.append({
            "变体": name,
            "年化": round(s["年化收益"] * 100, 2),
            "最大回撤": round(s["最大回撤"] * 100, 2),
            "夏普": round(s["夏普(rf=2%)"], 2),
            "卡玛": round(s["卡玛比率"], 2) if pd.notna(s["卡玛比率"]) else None,
            "月胜率": round(s["月胜率"] * 100, 1),
            "最差月": round(s["最差月份"] * 100, 2),
            "交易数": s["交易笔数"],
            "费用占比%": round(s["总费用"] / bt.init_cash * 100, 1),
        })
        print(rows[-1], flush=True)

    df = pd.DataFrame(rows).sort_values("卡玛", ascending=False)
    df.to_csv(os.path.join(HERE, "experiments.csv"), index=False)
    print("\n", df.to_string(index=False))


if __name__ == "__main__":
    main()
