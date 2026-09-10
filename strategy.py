"""策略信号层：月度动量轮动 + 大盘趋势择时 + 个股风控。

设计要点（都是 A 股实操里能落地的规则，不用未来数据）：
1. 选股：120 日中期动量强、近 20 日不过热（短期反转修正）、波动率不过高。
2. 过滤：股价站上 60 日均线、日均成交额达标、上市满 250 个交易日、非涨停日。
3. 择时：沪深 300 收盘价在 20 日均线上方才持仓，否则空仓（回避系统性下跌）。
4. 风控：个股回撤止损、跌破 20 日均线离场、单票权重上限。
所有信号只用截至当日收盘的数据，下一交易日开盘执行。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Params:
    # ---- 选股 ----
    hold_num: int = 10               # 持仓只数
    mom_window: int = 120            # 中期动量窗口（约半年）
    rev_window: int = 20             # 短期反转窗口
    vol_window: int = 20             # 波动率窗口
    mom_weight: float = 1.0
    rev_weight: float = 0.5          # 短期涨太多的扣分
    vol_weight: float = 0.3          # 高波动扣分
    trend_ma: int = 60               # 个股趋势均线
    min_history: int = 250           # 上市满一年
    min_amount: float = 1.0e8        # 20 日平均成交额下限（元）

    # ---- 择时 ----
    timing: bool = True              # 关闭后始终满仓（对照组）
    index_ma: int = 20               # 沪深300 择时均线
    index_code: str = "sh000300"

    # ---- 风控 ----
    stop_loss: float = 0.12          # 个股最大亏损
    trail_ma: int = 20               # 跌破该均线离场
    max_weight: float = 0.12         # 单票权重上限

    # ---- 调仓 ----
    rebalance: str = "M"             # M=每月末信号，W=每周末信号
    limit_pct: dict = field(default_factory=lambda: {"main": 0.10, "gem": 0.20})


def board_limit(code: str, params: Params) -> float:
    """涨跌停幅度：主板 10%，创业板/科创板 20%。"""
    if code.startswith(("300", "301", "688")):
        return params.limit_pct["gem"]
    return params.limit_pct["main"]


def compute_indicators(panel: dict[str, pd.DataFrame], params: Params) -> dict[str, pd.DataFrame]:
    close = panel["close"]
    volume = panel["volume"]
    amount = close * volume * 100.0  # 腾讯 volume 单位为手

    ind: dict[str, pd.DataFrame] = {}
    ind["mom"] = close / close.shift(params.mom_window) - 1.0
    ind["rev"] = close / close.shift(params.rev_window) - 1.0
    ind["vol"] = close.pct_change(fill_method=None).rolling(params.vol_window).std() * np.sqrt(252)
    ind["ma_trend"] = close.rolling(params.trend_ma).mean()
    ind["ma_trail"] = (
        close.rolling(params.trail_ma).mean()
        if params.trail_ma > 0
        else pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    )
    ind["amount20"] = amount.rolling(20).mean()
    ind["bars"] = close.notna().cumsum()
    return ind


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std()
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def select(
    day: pd.Timestamp,
    panel: dict[str, pd.DataFrame],
    ind: dict[str, pd.DataFrame],
    params: Params,
) -> list[str]:
    """给出该日收盘后的目标持仓列表（下一开盘买入）。"""
    close = panel["close"].loc[day]
    mom = ind["mom"].loc[day]
    rev = ind["rev"].loc[day]
    vol = ind["vol"].loc[day]

    ok = (
        close.notna()
        & mom.notna()
        & (ind["bars"].loc[day] >= params.min_history)
        & (ind["amount20"].loc[day] >= params.min_amount)
        & (close > ind["ma_trend"].loc[day])
        & (mom > 0)
    )
    cand = ok[ok].index
    if len(cand) == 0:
        return []

    score = (
        params.mom_weight * _zscore(mom[cand])
        - params.rev_weight * _zscore(rev[cand])
        - params.vol_weight * _zscore(vol[cand])
    )
    return score.sort_values(ascending=False).head(params.hold_num).index.tolist()


def market_on(day: pd.Timestamp, index_df: pd.DataFrame, params: Params) -> bool:
    """大盘择时开关：沪深 300 收盘价在均线上方视为可持仓。"""
    if not params.timing:
        return True
    s = index_df.loc[:day, "close"]
    if len(s) < params.index_ma:
        return False
    return bool(s.iloc[-1] > s.rolling(params.index_ma).mean().iloc[-1])


def rebalance_days(dates: pd.DatetimeIndex, freq: str) -> set[pd.Timestamp]:
    """每月/每周最后一个交易日作为信号日。"""
    s = pd.Series(dates, index=dates)
    return set(s.groupby(s.dt.to_period(freq)).max().tolist())
