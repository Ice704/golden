"""缠论三买策略：信号生成 + 回测。

交易规则
--------
买入（三买成立，T 日收盘确认，T+1 开盘市价买）
  1. 该股已形成中枢（连续三笔重叠区 ZD~ZG）
  2. 出现向上离开笔，笔的高点 > ZG * (1 + min_leave)
  3. 紧接着的回抽笔低点仍 > ZG（没有回到中枢里）
  4. 回抽笔的底分型被右侧 K 线确认，当日收盘发出信号
  5. 可选：沪深 300 在择时均线上方；成交额、上市时长过滤

卖出（任一条触发，T+1 开盘卖）
  a. 收盘价跌回中枢上沿 ZG 之下 —— 三买失效，这是最核心的止损位
  b. 相对买入价回撤超过 stop_loss
  c. 相对持仓期最高价回撤超过 trail_stop（保住浮盈）
  d. 该股出现三卖
  e. 大盘择时转空（可关闭）

仓位：等权 hold_num 份，单票不超过 max_weight。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import chan
from backtest import Costs, Trade
from strategy import Params, board_limit, market_on


@dataclass
class ChanParams:
    # ---- 缠论结构 ----
    min_gap: int = 3            # 成笔要求的最少合并 K 线间隔
    min_leave: float = 0.0      # 离开笔至少超出中枢上沿的幅度

    # ---- 组合 ----
    hold_num: int = 8
    max_weight: float = 0.15

    # ---- 过滤 ----
    min_history: int = 250
    min_amount: float = 5.0e7   # 20 日日均成交额下限（元）

    # ---- 择时 ----
    timing: bool = True
    index_ma: int = 20
    index_code: str = "sh000300"

    # ---- 风控 ----
    stop_loss: float = 0.10     # 相对买入价
    trail_stop: float = 0.15    # 相对持仓最高价
    zg_break: bool = True       # 跌破中枢上沿离场
    max_hold_days: int = 0      # >0 时超期强制离场

    limit_pct: dict = field(default_factory=lambda: {"main": 0.10, "gem": 0.20})


def _as_params(cp: ChanParams) -> Params:
    """复用 backtest 里依赖 Params 的工具函数（涨跌停、择时）。"""
    return Params(
        timing=cp.timing,
        index_ma=cp.index_ma,
        index_code=cp.index_code,
        limit_pct=cp.limit_pct,
    )


def build_signals(panel: dict[str, pd.DataFrame], cp: ChanParams) -> dict[str, pd.DataFrame]:
    """对每只股票做缠论分解，返回 {code: 信号表}。信号表列：kind, zg, zd。"""
    out: dict[str, pd.DataFrame] = {}
    high, low = panel["high"], panel["low"]
    for code in high.columns:
        df = pd.DataFrame({"high": high[code], "low": low[code]}).dropna()
        if len(df) < 60:
            continue
        sig = chan.signal_frame(df, min_gap=cp.min_gap, min_leave=cp.min_leave)
        if not sig.empty:
            out[code] = sig.set_index("date")
    return out


class ChanBacktester:
    """三买策略回测：T 日收盘确认信号，T+1 开盘成交，含全部交易摩擦。"""

    def __init__(
        self,
        panel: dict[str, pd.DataFrame],
        index_df: pd.DataFrame,
        cp: ChanParams,
        costs: Costs | None = None,
        init_cash: float = 1_000_000.0,
    ) -> None:
        self.panel = panel
        self.index_df = index_df.set_index("date") if "date" in index_df.columns else index_df
        self.cp = cp
        self.p = _as_params(cp)
        self.c = costs or Costs()
        self.init_cash = init_cash

        self.cash = init_cash
        self.pos: dict[str, dict] = {}
        self.trades: list[Trade] = []
        self.equity: list[tuple[pd.Timestamp, float]] = []

    # ---------- 交易成本 ----------
    def _buy_fee(self, amount: float) -> float:
        return max(amount * self.c.commission, self.c.min_commission) + amount * self.c.transfer_fee

    def _sell_fee(self, amount: float) -> float:
        return (
            max(amount * self.c.commission, self.c.min_commission)
            + amount * self.c.stamp_tax
            + amount * self.c.transfer_fee
        )

    def _tradable(self, code: str, day: pd.Timestamp, side: str) -> float | None:
        o = self.panel["open"].at[day, code]
        if not np.isfinite(o) or o <= 0:
            return None
        prev = self.panel["close"][code].loc[:day].iloc[:-1].dropna()
        if prev.empty:
            return None
        prev_close = float(prev.iloc[-1])
        lim = board_limit(code, self.p)
        if side == "buy" and o >= round(prev_close * (1 + lim), 2) - 1e-6:
            return None
        if side == "sell" and o <= round(prev_close * (1 - lim), 2) + 1e-6:
            return None
        return float(o)

    def _sell(self, code: str, day: pd.Timestamp, reason: str) -> bool:
        price = self._tradable(code, day, "sell")
        if price is None:
            return False
        price *= 1 - self.c.slippage
        shares = self.pos[code]["shares"]
        amount = price * shares
        fee = self._sell_fee(amount)
        self.cash += amount - fee
        self.trades.append(Trade(day, code, "sell", price, shares, amount, fee, reason))
        del self.pos[code]
        return True

    def _buy(self, code: str, day: pd.Timestamp, budget: float, zg: float, reason: str) -> bool:
        price = self._tradable(code, day, "buy")
        if price is None:
            return False
        price *= 1 + self.c.slippage
        shares = int(min(budget, self.cash) // (price * 100)) * 100
        if shares <= 0:
            return False
        amount = price * shares
        fee = self._buy_fee(amount)
        if amount + fee > self.cash:
            shares -= 100
            if shares <= 0:
                return False
            amount = price * shares
            fee = self._buy_fee(amount)
        self.cash -= amount + fee
        self.pos[code] = {
            "shares": shares,
            "cost_price": price,
            "high_price": price,
            "zg": zg,
            "days": 0,
        }
        self.trades.append(Trade(day, code, "buy", price, shares, amount, fee, reason))
        return True

    def _equity(self, day: pd.Timestamp) -> float:
        row = self.panel["close"].loc[day]
        value = self.cash
        for code, p in self.pos.items():
            px = row.get(code, np.nan)
            value += (float(px) if np.isfinite(px) else p["cost_price"]) * p["shares"]
        return float(value)

    # ---------- 主循环 ----------
    def run(self, start: str, end: str, signals: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
        cp = self.cp
        sig = signals if signals is not None else build_signals(self.panel, cp)

        close = self.panel["close"]
        amount20 = (close * self.panel["volume"] * 100.0).rolling(20).mean()
        bars_count = close.notna().cumsum()

        dates = close.loc[start:end].index
        pending_sell: list[tuple[str, str]] = []
        pending_buy: list[tuple[str, float]] = []

        for day in dates:
            # 1) 开盘执行昨日收盘产生的指令
            for code, reason in pending_sell:
                if code in self.pos:
                    self._sell(code, day, reason)
            pending_sell = []

            if pending_buy:
                eq = self._equity(day)
                budget = min(eq / cp.hold_num, eq * cp.max_weight)
                for code, zg in pending_buy:
                    if len(self.pos) >= cp.hold_num or self.cash < budget * 0.5:
                        break
                    if code in self.pos:
                        continue
                    self._buy(code, day, budget, zg, "buy3")
                pending_buy = []

            # 2) 收盘后更新持仓状态
            row = close.loc[day]
            for p in self.pos.values():
                p["days"] += 1
            for code, p in self.pos.items():
                px = row.get(code, np.nan)
                if np.isfinite(px):
                    p["high_price"] = max(p["high_price"], float(px))

            risk_off = not market_on(day, self.index_df, self.p)
            today_sig = {c: s.loc[day] for c, s in sig.items() if day in s.index}

            # 3) 卖出信号
            for code, p in list(self.pos.items()):
                px = row.get(code, np.nan)
                if not np.isfinite(px):
                    continue
                px = float(px)
                s = today_sig.get(code)
                kind = s["kind"] if s is not None else None
                if isinstance(kind, pd.Series):
                    kind = kind.iloc[0]
                if risk_off:
                    pending_sell.append((code, "market_off"))
                elif cp.zg_break and px < p["zg"]:
                    pending_sell.append((code, "back_into_zhongshu"))
                elif px <= p["cost_price"] * (1 - cp.stop_loss):
                    pending_sell.append((code, "stop_loss"))
                elif px <= p["high_price"] * (1 - cp.trail_stop):
                    pending_sell.append((code, "trail_stop"))
                elif kind == "sell3":
                    pending_sell.append((code, "sell3"))
                elif cp.max_hold_days > 0 and p["days"] >= cp.max_hold_days:
                    pending_sell.append((code, "time_exit"))

            # 4) 买入信号
            if not risk_off and len(self.pos) < cp.hold_num:
                held = set(self.pos) | {c for c, _ in pending_sell}
                cands: list[tuple[str, float, float]] = []
                for code, s in today_sig.items():
                    kind = s["kind"]
                    zg = s["zg"]
                    if isinstance(kind, pd.Series):   # 同日重复信号取第一条
                        kind, zg = kind.iloc[0], s["zg"].iloc[0]
                    if kind != "buy3" or code in held:
                        continue
                    px = row.get(code, np.nan)
                    if not np.isfinite(px) or float(px) < float(zg):
                        continue   # 收盘已跌回中枢，信号作废
                    if bars_count.at[day, code] < cp.min_history:
                        continue
                    amt = amount20.at[day, code]
                    if not np.isfinite(amt) or amt < cp.min_amount:
                        continue
                    # 排序打分：离中枢上沿越近，止损空间越小，优先
                    cands.append((code, float(px) / float(zg) - 1.0, float(zg)))
                cands.sort(key=lambda x: x[1])
                free = cp.hold_num - len(self.pos)
                pending_buy = [(c, zg) for c, _, zg in cands[:free]]

            self.equity.append((day, self._equity(day)))

        eq = pd.DataFrame(self.equity, columns=["date", "equity"]).set_index("date")
        eq["ret"] = eq["equity"].pct_change().fillna(0.0)
        return eq

    # ---------- 绩效 ----------
    def stats(self, eq: pd.DataFrame, bench: pd.Series | None = None) -> dict:
        from backtest import Backtester
        return Backtester.stats(self, eq, bench)   # 复用同一套指标口径
