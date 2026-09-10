"""缠论三买参数对照实验：看信号本身有没有 edge，以及各条规则的贡献。"""
from __future__ import annotations

import pandas as pd

from backtest import Costs
from chan_strategy import ChanBacktester, ChanParams, build_signals
from run_chan import load

START, END = "2016-01-01", "2026-09-10"

VARIANTS: list[tuple[str, dict]] = [
    ("基准(择时+中枢止损+双止损)", {}),
    ("无大盘择时", {"timing": False}),
    ("无中枢破位离场", {"zg_break": False}),
    ("无移动止损", {"trail_stop": 1.0}),
    ("止损 15%", {"stop_loss": 0.15}),
    ("持仓 5 只", {"hold_num": 5}),
    ("持仓 15 只", {"hold_num": 15}),
    ("笔间隔 5 根(更严)", {"min_gap": 5}),
    ("离开中枢需 >3%", {"min_leave": 0.03}),
    ("择时用 60 日均线", {"index_ma": 60}),
    ("持有上限 60 日", {"max_hold_days": 60}),
]

KEEP = ["总收益", "年化收益", "最大回撤", "夏普(rf=2%)", "卡玛比率", "月胜率", "交易笔数", "个股胜率", "总费用"]


def main() -> None:
    panel, idx, n = load(START, END, 500)
    bench = idx.set_index("date")["close"] if "date" in idx.columns else idx["close"]
    print(f"股票池 {n} 只")

    sig_cache: dict[tuple[int, float], dict] = {}
    rows = []
    for name, kw in VARIANTS:
        cp = ChanParams(**kw)
        key = (cp.min_gap, cp.min_leave)
        if key not in sig_cache:
            sig_cache[key] = build_signals(panel, cp)
        bt = ChanBacktester(panel, idx, cp, Costs())
        eq = bt.run(START, END, signals=sig_cache[key])
        st = bt.stats(eq, bench)
        rows.append({"变体": name, **{k: st[k] for k in KEEP}})
        print(f"{name:<24} 年化 {st['年化收益']:.2%}  回撤 {st['最大回撤']:.2%}  夏普 {st['夏普(rf=2%)']:.2f}")

    df = pd.DataFrame(rows)
    df.to_csv("chan_experiments.csv", index=False)
    print("\n" + df.to_string(index=False))


if __name__ == "__main__":
    main()
