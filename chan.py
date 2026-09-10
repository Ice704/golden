"""缠论结构：K 线包含处理 → 分型 → 笔 → 中枢 → 三类买卖点。

严格按缠论定义逐层构建，全部只用截至当日的数据，不含未来函数。

术语对照
--------
包含处理  相邻两根 K 线高低点互相包含时合并为一根，方向由前一根趋势决定
分型      三根处理后 K 线，中间那根高点最高 = 顶分型，低点最低 = 底分型
笔        相邻的顶分型与底分型之间，中间至少隔 1 根独立 K 线（新笔标准）
中枢      连续三笔的重叠区间：ZG = min(三笔高点)，ZD = max(三笔低点)，要求 ZG > ZD
三买      价格向上离开中枢后，回抽笔的最低点仍在 ZG 之上，回抽结束转折向上时成立
三卖      价格向下离开中枢后，反抽笔的最高点仍在 ZD 之下
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MergedBar:
    """包含处理后的合并 K 线。"""
    idx: int          # 原始序列下标（合并区间的最后一根）
    start_idx: int    # 合并区间的第一根
    high: float
    low: float


@dataclass
class Fractal:
    """分型：kind = 1 顶分型，-1 底分型。"""
    pos: int          # 在 merged 序列中的位置
    idx: int          # 原始序列下标
    kind: int
    price: float      # 顶分型取高点，底分型取低点


@dataclass
class Bi:
    """笔：direction = 1 向上笔（底->顶），-1 向下笔（顶->底）。"""
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    direction: int

    @property
    def high(self) -> float:
        return max(self.start_price, self.end_price)

    @property
    def low(self) -> float:
        return min(self.start_price, self.end_price)


@dataclass
class Zhongshu:
    """中枢：由 bis[i:i+3] 及后续延伸笔构成。"""
    start_bi: int
    end_bi: int
    zg: float         # 中枢上沿
    zd: float         # 中枢下沿
    start_idx: int
    end_idx: int


def merge_bars(high: np.ndarray, low: np.ndarray) -> list[MergedBar]:
    """K 线包含关系处理。"""
    bars: list[MergedBar] = []
    for i in range(len(high)):
        h, low_i = float(high[i]), float(low[i])
        if not np.isfinite(h) or not np.isfinite(low_i):
            continue
        if len(bars) < 2:
            bars.append(MergedBar(i, i, h, low_i))
            continue
        prev = bars[-1]
        contained = (h <= prev.high and low_i >= prev.low) or (h >= prev.high and low_i <= prev.low)
        if not contained:
            bars.append(MergedBar(i, i, h, low_i))
            continue
        up = prev.high > bars[-2].high  # 前一段方向
        if up:
            new_h, new_l = max(h, prev.high), max(low_i, prev.low)
        else:
            new_h, new_l = min(h, prev.high), min(low_i, prev.low)
        bars[-1] = MergedBar(i, prev.start_idx, new_h, new_l)
    return bars


def find_fractals(bars: list[MergedBar]) -> list[Fractal]:
    """在合并 K 线上找顶/底分型。"""
    out: list[Fractal] = []
    for i in range(1, len(bars) - 1):
        a, b, c = bars[i - 1], bars[i], bars[i + 1]
        if b.high > a.high and b.high > c.high:
            out.append(Fractal(i, b.idx, 1, b.high))
        elif b.low < a.low and b.low < c.low:
            out.append(Fractal(i, b.idx, -1, b.low))
    return out


def build_bis(bars: list[MergedBar], fractals: list[Fractal], min_gap: int = 3) -> list[Bi]:
    """由分型连成笔：方向必须交替，两端分型之间至少间隔 min_gap 根合并 K 线。

    同向分型相邻时保留更极端的那个（顶取更高、底取更低）。
    """
    if not fractals:
        return []
    kept: list[Fractal] = [fractals[0]]
    for f in fractals[1:]:
        last = kept[-1]
        if f.kind == last.kind:
            if (f.kind == 1 and f.price > last.price) or (f.kind == -1 and f.price < last.price):
                kept[-1] = f
            continue
        if f.pos - last.pos < min_gap:
            # 间隔不足，不能成笔；若新分型更极端则替换掉上一个同向端点
            continue
        kept.append(f)

    bis: list[Bi] = []
    for a, b in zip(kept, kept[1:]):
        bis.append(Bi(a.idx, b.idx, a.price, b.price, 1 if b.kind == 1 else -1))
    return bis


def build_zhongshus(bis: list[Bi]) -> list[Zhongshu]:
    """连续三笔重叠构成中枢，同方向后续笔继续延伸中枢。"""
    zs: list[Zhongshu] = []
    i = 0
    while i + 2 < len(bis):
        a, b, c = bis[i], bis[i + 1], bis[i + 2]
        zg = min(a.high, b.high, c.high)
        zd = max(a.low, b.low, c.low)
        if zg <= zd:
            i += 1
            continue
        end = i + 2
        # 延伸：后续笔仍在中枢区间来回则并入；一旦出现"离开笔 + 不回中枢的回抽"则中枢结束
        while end + 1 < len(bis):
            nxt = bis[end + 1]
            back = bis[end + 2] if end + 2 < len(bis) else None
            leaves_up = nxt.direction == 1 and nxt.high > zg and back is not None and back.low > zg
            leaves_dn = nxt.direction == -1 and nxt.low < zd and back is not None and back.high < zd
            if leaves_up or leaves_dn:
                break
            if nxt.low <= zg and nxt.high >= zd:
                end += 1
            else:
                break
        zs.append(Zhongshu(i, end, zg, zd, bis[i].start_idx, bis[end].end_idx))
        i = end + 1
    return zs


@dataclass
class Signal:
    idx: int          # 信号确认的原始 K 线下标
    kind: str         # "buy3" / "sell3"
    zg: float
    zd: float
    price: float


def find_third_signals(bis: list[Bi], zs_list: list[Zhongshu], min_leave: float = 0.0) -> list[Signal]:
    """三买 / 三卖。

    三买：中枢结束后出现向上离开笔（高点 > ZG），紧接着的向下回抽笔低点仍 > ZG，
          该回抽笔结束（底分型确认）即为三买，确认点为回抽笔的终点 K 线。
    三卖：对称定义。
    min_leave：要求离开笔至少突破中枢上沿的幅度（0.02 = 2%），过滤毛刺。
    """
    out: list[Signal] = []
    for zs in zs_list:
        j = zs.end_bi + 1
        if j + 1 >= len(bis):
            continue
        leave, pull = bis[j], bis[j + 1]
        if leave.direction == 1 and pull.direction == -1:
            if leave.end_price > zs.zg * (1 + min_leave) and pull.end_price > zs.zg:
                out.append(Signal(pull.end_idx, "buy3", zs.zg, zs.zd, pull.end_price))
        elif leave.direction == -1 and pull.direction == 1:
            if leave.end_price < zs.zd * (1 - min_leave) and pull.end_price < zs.zd:
                out.append(Signal(pull.end_idx, "sell3", zs.zg, zs.zd, pull.end_price))
    return out


def analyze(df: pd.DataFrame, min_gap: int = 3, min_leave: float = 0.0) -> dict:
    """对单只股票的日线做完整缠论分解。df 需含 high/low 列，按日期升序。"""
    bars = merge_bars(df["high"].to_numpy(), df["low"].to_numpy())
    fractals = find_fractals(bars)
    bis = build_bis(bars, fractals, min_gap=min_gap)
    zs_list = build_zhongshus(bis)
    signals = find_third_signals(bis, zs_list, min_leave=min_leave)
    return {"bars": bars, "fractals": fractals, "bis": bis, "zhongshus": zs_list, "signals": signals}


def signal_frame(df: pd.DataFrame, **kw) -> pd.DataFrame:
    """把三买/三卖信号还原成按日期索引的表，供回测逐日读取。

    注意：笔的终点要等右侧分型确认才成立，这里用 confirm_idx（终点后再走 2 根合并 K 线）
    作为真正可交易的日期，避免用到未来数据。
    """
    res = analyze(df, **kw)
    bars = res["bars"]
    idx_to_pos = {b.idx: p for p, b in enumerate(bars)}
    rows = []
    for s in res["signals"]:
        pos = idx_to_pos.get(s.idx)
        if pos is None or pos + 2 >= len(bars):
            continue
        confirm_idx = bars[pos + 2].idx   # 底分型需右侧两根合并 K 线确认
        rows.append({
            "date": df.index[confirm_idx],
            "kind": s.kind,
            "zg": s.zg,
            "zd": s.zd,
            "signal_price": s.price,
        })
    return pd.DataFrame(rows)
