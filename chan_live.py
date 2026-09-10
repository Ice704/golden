"""缠论三买实盘信号：每个交易日收盘后跑一次，输出次日开盘的委托清单。

用法:
    python3 chan_live.py --positions positions.json
positions.json 记录实际持仓（cost_price 用于止损，zg 为买入时的中枢上沿）:
    {"cash": 100000,
     "positions": {"600519": {"shares": 100, "cost_price": 1500.0, "zg": 1480.0, "high_price": 1600.0}}}
输出 chan_orders_YYYY-MM-DD.csv，次日 9:30 后照单执行。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

import numpy as np
import pandas as pd

import data
from chan_strategy import ChanParams, build_signals, _as_params
from strategy import market_on

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", default=os.path.join(HERE, "positions.json"))
    ap.add_argument("--top-n", type=int, default=500)
    ap.add_argument("--hold", type=int, default=8)
    ap.add_argument("--min-gap", type=int, default=3)
    ap.add_argument("--start", default="2022-01-01", help="缠论结构回溯起点")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()

    today = date.today().strftime("%Y-%m-%d")
    cp = ChanParams(hold_num=a.hold, min_gap=a.min_gap)

    uni = data.build_universe(a.top_n, force=a.refresh)
    px = data.fetch_daily(uni["code"].tolist(), start=a.start, end=today, force=a.refresh)
    idx = data.fetch_index("sh000300", a.start, today)
    panel = data.to_panel(px)
    close = panel["close"]
    day = close.index[-1]
    row = close.loc[day]
    name_map = dict(zip(uni["code"], uni["name"]))

    state = {"cash": 0.0, "positions": {}}
    if os.path.exists(a.positions):
        with open(a.positions) as f:
            state = json.load(f)
    pos: dict[str, dict] = state.get("positions", {})

    risk_on = market_on(day, idx.set_index("date"), _as_params(cp))
    sig = build_signals(panel, cp)
    today_sig = {c: s.loc[day] for c, s in sig.items() if day in s.index}

    orders = []
    # 1) 卖出
    for code, p in pos.items():
        now = row.get(code, np.nan)
        if not np.isfinite(now):
            continue
        now = float(now)
        kind = today_sig[code]["kind"] if code in today_sig else None
        zg = float(p.get("zg", 0.0))
        high = float(p.get("high_price", p["cost_price"]))
        reason = None
        if not risk_on:
            reason = f"沪深300 跌破{cp.index_ma}日均线，清仓"
        elif cp.zg_break and now < zg:
            reason = f"跌回中枢上沿 {zg:.2f}，三买失效"
        elif now <= p["cost_price"] * (1 - cp.stop_loss):
            reason = f"止损 -{cp.stop_loss:.0%}"
        elif now <= high * (1 - cp.trail_stop):
            reason = f"较持仓最高价回撤 {cp.trail_stop:.0%}"
        elif kind == "sell3":
            reason = "出现三卖"
        if reason:
            orders.append({"code": code, "name": name_map.get(code, ""), "side": "SELL",
                           "shares": p["shares"], "ref_price": round(now, 2), "reason": reason})

    # 2) 三买买入
    sells = {o["code"] for o in orders}
    if risk_on:
        equity = state.get("cash", 0.0) + sum(
            float(row.get(c, 0) or 0) * p["shares"] for c, p in pos.items()
        )
        budget = min(equity / cp.hold_num, equity * cp.max_weight) if equity > 0 else 0.0
        free = cp.hold_num - (len(pos) - len(sells))
        cands = []
        for code, s in today_sig.items():
            if s["kind"] != "buy3" or code in pos:
                continue
            now = row.get(code, np.nan)
            if not np.isfinite(now) or float(now) < float(s["zg"]):
                continue
            cands.append((code, float(now) / float(s["zg"]) - 1.0, float(s["zg"]), float(now)))
        cands.sort(key=lambda x: x[1])
        for code, _, zg, now in cands[: max(free, 0)]:
            shares = int(budget // (now * 100)) * 100
            orders.append({"code": code, "name": name_map.get(code, ""), "side": "BUY",
                           "shares": shares, "ref_price": round(now, 2),
                           "reason": f"三买成立（中枢上沿 {zg:.2f}，此价即止损位）"})

    df = pd.DataFrame(orders)
    out = os.path.join(HERE, f"chan_orders_{day.date()}.csv")
    df.to_csv(out, index=False)

    n_buy3 = sum(1 for s in today_sig.values() if s["kind"] == "buy3")
    print(f"信号日 {day.date()}   大盘: {'可持仓' if risk_on else '空仓'}   今日三买 {n_buy3} 个")
    print(df.to_string(index=False) if not df.empty else "今日无委托")
    print(f"\n已写入 {out}（次日 9:30 后执行；开盘一字涨停则放弃，跌停则次日再卖）")


if __name__ == "__main__":
    main()
