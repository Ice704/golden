"""缠论结构算法的最小验证：用构造的价格序列检查分型/笔/中枢/三买。"""
from __future__ import annotations

import numpy as np
import pandas as pd

import chan


def make_zigzag(points: list[tuple[int, float]]) -> pd.DataFrame:
    """在给定拐点之间线性插值，生成一段有明确笔结构的行情。"""
    xs = np.arange(points[0][0], points[-1][0] + 1)
    ys = np.interp(xs, [p[0] for p in points], [p[1] for p in points])
    idx = pd.bdate_range("2020-01-01", periods=len(xs))
    return pd.DataFrame(
        {"high": ys * 1.005, "low": ys * 0.995, "close": ys, "open": ys}, index=idx
    )


def test_merge_removes_containment() -> None:
    high = np.array([10.0, 11.0, 10.8, 12.0])
    low = np.array([9.0, 9.5, 9.6, 10.0])
    bars = chan.merge_bars(high, low)
    assert len(bars) == 3                       # 第 3 根被第 2 根包含，合并
    assert bars[1].high == 11.0 and bars[1].low == 9.6   # 向上时取高高、低低中的高


def test_fractals_and_bis() -> None:
    df = make_zigzag([(0, 10), (10, 14), (20, 11), (30, 16), (40, 12)])
    res = chan.analyze(df)
    kinds = [f.kind for f in res["fractals"]]
    assert 1 in kinds and -1 in kinds
    dirs = [b.direction for b in res["bis"]]
    assert all(a != b for a, b in zip(dirs, dirs[1:]))   # 方向必须交替
    assert len(res["bis"]) >= 2


def test_zhongshu_range() -> None:
    # 三笔在 11~14 区间来回震荡，形成中枢
    df = make_zigzag([(0, 10), (10, 14), (20, 11), (30, 13.5), (40, 11.5), (50, 13)])
    res = chan.analyze(df)
    assert res["zhongshus"], "应识别出中枢"
    z = res["zhongshus"][0]
    assert z.zd < z.zg
    assert 10.5 <= z.zd <= 12.5 and 12.5 <= z.zg <= 14.5


def test_third_buy() -> None:
    # 中枢(11~14) -> 向上离开到 18 -> 回抽只到 15（不回中枢）-> 三买
    df = make_zigzag(
        [(0, 10), (10, 14), (20, 11), (30, 13.5), (40, 11.5), (50, 18), (60, 15), (70, 20)]
    )
    res = chan.analyze(df)
    buys = [s for s in res["signals"] if s.kind == "buy3"]
    assert buys, "应识别出三买"
    b = buys[0]
    assert df["low"].iloc[b.idx] > b.zg      # 回抽低点在中枢上沿之上

    sig = chan.signal_frame(df)
    assert not sig.empty
    assert sig["date"].iloc[0] > df.index[b.idx]   # 确认日晚于回抽低点，无未来函数


def test_no_signal_without_zhongshu() -> None:
    # 单边上涨，没有三笔重叠，不应有三买
    df = make_zigzag([(0, 10), (20, 20), (40, 18), (60, 30)])
    res = chan.analyze(df)
    assert not [s for s in res["signals"] if s.kind == "buy3"]


def test_third_sell() -> None:
    df = make_zigzag(
        [(0, 14), (10, 11), (20, 13.5), (30, 11.5), (40, 13), (50, 8), (60, 10), (70, 6)]
    )
    res = chan.analyze(df)
    assert [s for s in res["signals"] if s.kind == "sell3"], "应识别出三卖"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if fails else 0)
