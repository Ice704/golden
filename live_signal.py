"""实盘信号生成：每天收盘后跑一次，输出明天开盘要执行的委托清单。

用法:
    python3 live_signal.py --positions positions.json
positions.json 记录你的实际持仓（买入均价用于止损判定）:
    {"cash": 100000, "positions": {"600519": {"shares": 100, "cost_price": 1500.0}}}
输出 orders_YYYY-MM-DD.csv，可直接照单在券商 App / QMT 里下单。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

import numpy as np
import pandas as pd

import data
from strategy import Params, compute_indicators, market_on, rebalance_days, select

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", default=os.path.join(HERE, "positions.json"))
    ap.add_argument("--top-n", type=int, default=500)
    ap.add_argument("--hold", type=int, default=10)
    ap.add_argument("--refresh", action="store_true", help="重新抓取行情")
    args = ap.parse_args()

    today = date.today().strftime("%Y-%m-%d")
    params = Params(hold_num=args.hold)

    uni = data.build_universe(args.top_n, force=args.refresh)
    px = data.fetch_daily(uni["code"].tolist(), start="2023-01-01", end=today, force=args.refresh)
    idx = data.fetch_index("sh000300", "2023-01-01", today)
    panel = data.to_panel(px)
    ind = compute_indicators(panel, params)

    day = panel["close"].index[-1]
    close = panel["close"].loc[day]
    name_map = dict(zip(uni["code"], uni["name"]))

    state = {"cash": 0.0, "positions": {}}
    if os.path.exists(args.positions):
        with open(args.positions) as f:
            state = json.load(f)
    pos = state.get("positions", {})

    risk_on = market_on(day, idx.set_index("date"), params)
    is_rb = day in rebalance_days(panel["close"].index, params.rebalance)
    target = select(day, panel, ind, params) if (risk_on and is_rb) else []

    orders = []
    # 1) 风控卖出
    for code, p in pos.items():
        px_now = close.get(code, np.nan)
        ma = ind["ma_trail"].at[day, code] if code in ind["ma_trail"].columns else np.nan
        if not np.isfinite(px_now):
            continue
        reason = None
        if not risk_on:
            reason = "大盘跌破均线，清仓"
        elif px_now <= p["cost_price"] * (1 - params.stop_loss):
            reason = f"止损 -{params.stop_loss:.0%}"
        elif np.isfinite(ma) and px_now < ma:
            reason = f"跌破{params.trail_ma}日均线"
        elif is_rb and target and code not in target:
            reason = "调仓换出"
        if reason:
            orders.append({"code": code, "name": name_map.get(code, ""), "side": "SELL",
                           "shares": p["shares"], "ref_price": round(float(px_now), 2), "reason": reason})

    # 2) 调仓买入
    if risk_on and is_rb and target:
        keep = [c for c in pos if c in target]
        buys = [c for c in target if c not in keep]
        equity = state.get("cash", 0.0) + sum(
            float(close.get(c, 0)) * p["shares"] for c, p in pos.items()
        )
        budget = equity / params.hold_num if equity > 0 else 0.0
        for code in buys:
            px_now = float(close.get(code, np.nan))
            shares = int(budget // (px_now * 100)) * 100 if np.isfinite(px_now) and px_now > 0 else 0
            orders.append({"code": code, "name": name_map.get(code, ""), "side": "BUY",
                           "shares": shares, "ref_price": round(px_now, 2), "reason": "月度动量入选"})

    df = pd.DataFrame(orders)
    out = os.path.join(HERE, f"orders_{day.date()}.csv")
    df.to_csv(out, index=False)

    print(f"信号日: {day.date()}   大盘状态: {'可持仓' if risk_on else '空仓'}   调仓日: {is_rb}")
    if target:
        print("目标持仓:", ", ".join(f"{c}({name_map.get(c, '')})" for c in target))
    print(df.to_string(index=False) if not df.empty else "今日无委托")
    print(f"\n已写入 {out}（次日开盘后 9:30-9:35 分批执行）")


if __name__ == "__main__":
    main()
