"""回测入口：python3 run_backtest.py [--start 2016-01-01] [--end 2026-09-10]"""
from __future__ import annotations

import argparse
import json
import os

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import data  # noqa: E402
from backtest import Backtester, Costs  # noqa: E402
from strategy import Params  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


DATA_START = "2014-06-01"


def load(start: str, end: str, top_n: int):
    uni_path = os.path.join(data.CACHE_DIR, f"universe{top_n}.parquet")
    if os.path.exists(uni_path):
        uni = pd.read_parquet(uni_path)
    else:
        uni = data.build_universe(top_n)
        uni.to_parquet(uni_path)
    px = data.fetch_daily(uni["code"].tolist(), start=DATA_START, end=end)
    idx = data.fetch_index("sh000300", DATA_START, end)
    return data.to_panel(px), idx


RATIO_KEYS = {
    "总收益", "年化收益", "年化波动", "最大回撤", "月胜率", "最好月份", "最差月份",
    "月收益中位数", "个股胜率", "单笔平均收益", "持仓天数占比", "基准总收益(沪深300)",
    "基准年化", "基准最大回撤",
}


def fmt(key: str, value) -> str:
    if isinstance(value, float):
        if key in RATIO_KEYS:
            return f"{value:.2%}"
        return f"{value:.2f}"
    return str(value)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--top-n", type=int, default=1200)
    ap.add_argument("--hold", type=int, default=10)
    ap.add_argument("--cash", type=float, default=1_000_000)
    ap.add_argument("--no-timing", action="store_true", help="关闭大盘择时做对照")
    ap.add_argument("--no-ma-exit", action="store_true", help="关闭跌破均线离场")
    ap.add_argument("--rebalance", default="M", choices=["M", "W"])
    ap.add_argument("--index-ma", type=int, default=20)
    ap.add_argument("--stop-loss", type=float, default=0.12)
    ap.add_argument("--tag", default="base")
    args = ap.parse_args()

    panel, idx = load(args.start, args.end, args.top_n)
    params = Params(
        hold_num=args.hold,
        rebalance=args.rebalance,
        index_ma=args.index_ma,
        stop_loss=args.stop_loss,
    )
    if args.no_ma_exit:
        params.trail_ma = 0
    if args.no_timing:
        params.timing = False

    bt = Backtester(panel, idx, params, Costs(), init_cash=args.cash)
    eq = bt.run(args.start, args.end)

    bench = idx.set_index("date")["close"]
    stats = bt.stats(eq, bench)
    print(f"\n===== 回测结果 [{args.tag}] =====")
    for k, v in stats.items():
        print(f"{k:>18}: {fmt(k, v)}")

    eq.to_csv(os.path.join(HERE, f"equity_{args.tag}.csv"))
    pd.DataFrame([{
        "date": t.date, "code": t.code, "side": t.side, "price": round(t.price, 3),
        "shares": t.shares, "amount": round(t.amount, 2), "fee": round(t.fee, 2), "reason": t.reason,
    } for t in bt.trades]).to_csv(os.path.join(HERE, f"trades_{args.tag}.csv"), index=False)
    with open(os.path.join(HERE, f"stats_{args.tag}.json"), "w") as f:
        json.dump({k: (str(v) if not isinstance(v, float) else round(v, 6)) for k, v in stats.items()},
                  f, ensure_ascii=False, indent=2)

    b = bench.reindex(eq.index).ffill()
    fig, ax = plt.subplots(2, 1, figsize=(11, 8), sharex=True, height_ratios=[3, 1])
    ax[0].plot(eq.index, eq["equity"] / eq["equity"].iloc[0], label="Strategy", lw=1.6)
    ax[0].plot(b.index, b / b.iloc[0], label="CSI300", lw=1.2, alpha=0.8)
    ax[0].set_yscale("log")
    ax[0].set_title(f"A-share momentum rotation  {args.start} ~ {args.end}  "
                    f"CAGR={stats['年化收益']:.2%}  MDD={stats['最大回撤']:.2%}")
    ax[0].legend()
    ax[0].grid(alpha=0.3)
    dd = eq["equity"] / eq["equity"].cummax() - 1
    ax[1].fill_between(eq.index, dd, 0, color="crimson", alpha=0.5)
    ax[1].set_ylabel("drawdown")
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, f"equity_{args.tag}.png"), dpi=130)
    print(f"\n输出: equity_{args.tag}.png / equity_{args.tag}.csv / trades_{args.tag}.csv")


if __name__ == "__main__":
    main()
