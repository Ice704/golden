"""画缠论结构图：K 线 + 笔 + 中枢区间 + 三买/三卖点。

用法：python3 plot_chan.py 600519 --start 2020-01-01 --end 2022-12-31
"""
from __future__ import annotations

import argparse
import os

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

import chan  # noqa: E402
import data  # noqa: E402


def load_stock(code: str, start: str, end: str) -> pd.DataFrame:
    path = os.path.join(data.CACHE_DIR, "stocks", f"{code}.parquet")
    if os.path.exists(path):
        df = pd.read_parquet(path)
    else:
        cache = os.path.join(data.CACHE_DIR, "daily_2015-01-01_2026-09-10_500.parquet")
        df = pd.read_parquet(cache)
        df = df[df["code"] == code]
    if df.empty:
        raise SystemExit(f"没有 {code} 的行情缓存")
    df = df.set_index("date").sort_index().loc[start:end]
    return df[["open", "high", "low", "close"]].dropna()


def plot(code: str, df: pd.DataFrame, out: str, min_gap: int = 3, min_leave: float = 0.0) -> None:
    res = chan.analyze(df, min_gap=min_gap, min_leave=min_leave)
    x = range(len(df))
    fig, ax = plt.subplots(figsize=(16, 8))

    # K 线
    for i, (_, r) in enumerate(df.iterrows()):
        up = r["close"] >= r["open"]
        color = "#d62728" if up else "#2ca02c"
        ax.vlines(i, r["low"], r["high"], color=color, linewidth=0.6)
        ax.add_patch(
            Rectangle(
                (i - 0.3, min(r["open"], r["close"])),
                0.6,
                max(abs(r["close"] - r["open"]), 1e-6),
                facecolor=color if up else color,
                edgecolor=color,
                alpha=0.7,
            )
        )

    # 笔
    for b in res["bis"]:
        ax.plot([b.start_idx, b.end_idx], [b.start_price, b.end_price], color="#1f77b4", lw=1.4)

    # 中枢
    for z in res["zhongshus"]:
        ax.add_patch(
            Rectangle(
                (z.start_idx, z.zd),
                max(z.end_idx - z.start_idx, 1),
                z.zg - z.zd,
                facecolor="#ff7f0e",
                alpha=0.18,
                edgecolor="#ff7f0e",
            )
        )

    # 三买 / 三卖
    for s in res["signals"]:
        if s.kind == "buy3":
            ax.scatter(s.idx, s.price * 0.98, marker="^", s=150, color="red", zorder=5)
            ax.annotate("B3", (s.idx, s.price * 0.96), color="red", ha="center", fontsize=9)
        else:
            ax.scatter(s.idx, s.price * 1.02, marker="v", s=150, color="green", zorder=5)
            ax.annotate("S3", (s.idx, s.price * 1.04), color="green", ha="center", fontsize=9)

    ticks = list(x)[:: max(len(df) // 12, 1)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([df.index[i].strftime("%Y-%m") for i in ticks], rotation=45)
    ax.set_title(f"{code}  bi={len(res['bis'])}  zhongshu={len(res['zhongshus'])}  signals={len(res['signals'])}")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print(f"saved {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2022-12-31")
    ap.add_argument("--min-gap", type=int, default=3)
    ap.add_argument("--min-leave", type=float, default=0.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    df = load_stock(a.code, a.start, a.end)
    plot(a.code, df, a.out or f"chan_{a.code}.png", a.min_gap, a.min_leave)


if __name__ == "__main__":
    main()
