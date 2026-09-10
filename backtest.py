"""日频回测引擎：T 日收盘出信号，T+1 开盘成交，含真实交易摩擦。

摩擦项：
- 佣金 万 2.5，单边最低 5 元
- 印花税 千 1（仅卖出）
- 过户费 万 0.1（双边）
- 滑点 0.1%（买入上浮 / 卖出下压）
- 一手 100 股整数倍
- 停牌（无行情）不可交易；开盘涨停不可买、开盘跌停不可卖
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategy import Params, board_limit, compute_indicators, market_on, rebalance_days, select


@dataclass
class Costs:
    commission: float = 0.00025
    min_commission: float = 5.0
    stamp_tax: float = 0.001
    transfer_fee: float = 0.00001
    slippage: float = 0.001


@dataclass
class Trade:
    date: pd.Timestamp
    code: str
    side: str
    price: float
    shares: int
    amount: float
    fee: float
    reason: str


class Backtester:
    def __init__(
        self,
        panel: dict[str, pd.DataFrame],
        index_df: pd.DataFrame,
        params: Params,
        costs: Costs | None = None,
        init_cash: float = 1_000_000.0,
    ) -> None:
        self.panel = panel
        self.index_df = index_df.set_index("date") if "date" in index_df.columns else index_df
        self.p = params
        self.c = costs or Costs()
        self.init_cash = init_cash

        self.cash = init_cash
        self.pos: dict[str, dict] = {}   # code -> {shares, cost_price, high_price}
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

    # ---------- 可交易判定 ----------
    def _tradable(self, code: str, day: pd.Timestamp, side: str) -> float | None:
        o = self.panel["open"].at[day, code]
        if not np.isfinite(o) or o <= 0:
            return None  # 停牌
        prev = self.panel["close"][code].loc[:day].iloc[:-1]
        if prev.empty:
            return None
        prev_close = prev.dropna().iloc[-1] if prev.notna().any() else np.nan
        if not np.isfinite(prev_close):
            return None
        lim = board_limit(code, self.p)
        up = round(prev_close * (1 + lim), 2)
        down = round(prev_close * (1 - lim), 2)
        if side == "buy" and o >= up - 1e-6:
            return None   # 一字/开盘涨停买不到
        if side == "sell" and o <= down + 1e-6:
            return None   # 开盘跌停卖不掉
        return float(o)

    # ---------- 下单 ----------
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

    def _buy(self, code: str, day: pd.Timestamp, budget: float, reason: str) -> bool:
        price = self._tradable(code, day, "buy")
        if price is None:
            return False
        price *= 1 + self.c.slippage
        shares = int(budget // (price * 100)) * 100
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
        self.pos[code] = {"shares": shares, "cost_price": price, "high_price": price}
        self.trades.append(Trade(day, code, "buy", price, shares, amount, fee, reason))
        return True

    # ---------- 主循环 ----------
    def run(self, start: str, end: str) -> pd.DataFrame:
        ind = compute_indicators(self.panel, self.p)
        dates = self.panel["close"].loc[start:end].index
        rb = rebalance_days(dates, self.p.rebalance)

        pending_target: list[str] | None = None
        pending_sell: list[tuple[str, str]] = []

        for i, day in enumerate(dates):
            # 1) 执行上一交易日收盘产生的指令（今日开盘价）
            for code, reason in pending_sell:
                if code in self.pos:
                    self._sell(code, day, reason)
            pending_sell = []

            if pending_target is not None:
                for code in list(self.pos):
                    if code not in pending_target:
                        self._sell(code, day, "rebalance_out")
                equity = self._equity(day)
                slots = [c for c in pending_target if c not in self.pos]
                free_slots = self.p.hold_num - len(self.pos)
                if free_slots > 0 and slots:
                    budget = min(equity / self.p.hold_num, equity * self.p.max_weight)
                    for code in slots[:free_slots]:
                        if self.cash < budget * 0.5:
                            break
                        self._buy(code, day, min(budget, self.cash), "rebalance_in")
                pending_target = None

            # 2) 收盘后更新持仓状态与风控信号
            close_row = self.panel["close"].loc[day]
            for code, p in self.pos.items():
                px = close_row.get(code, np.nan)
                if np.isfinite(px):
                    p["high_price"] = max(p["high_price"], float(px))

            risk_off = not market_on(day, self.index_df, self.p)
            for code, p in list(self.pos.items()):
                px = close_row.get(code, np.nan)
                if not np.isfinite(px):
                    continue
                ma = ind["ma_trail"].at[day, code]
                if risk_off:
                    pending_sell.append((code, "market_off"))
                elif px <= p["cost_price"] * (1 - self.p.stop_loss):
                    pending_sell.append((code, "stop_loss"))
                elif np.isfinite(ma) and px < ma:
                    pending_sell.append((code, "below_ma"))

            # 3) 调仓信号
            if day in rb and not risk_off:
                target = select(day, self.panel, ind, self.p)
                stops = {c for c, _ in pending_sell}
                pending_target = [c for c in target if c not in stops]
                pending_sell = [(c, r) for c, r in pending_sell if c not in set(target)]

            self.equity.append((day, self._equity(day)))

        eq = pd.DataFrame(self.equity, columns=["date", "equity"]).set_index("date")
        eq["ret"] = eq["equity"].pct_change().fillna(0.0)
        return eq

    def _equity(self, day: pd.Timestamp) -> float:
        close_row = self.panel["close"].loc[day]
        value = self.cash
        for code, p in self.pos.items():
            px = close_row.get(code, np.nan)
            if not np.isfinite(px):
                px = p["cost_price"]
            value += px * p["shares"]
        return float(value)

    # ---------- 绩效 ----------
    def stats(self, eq: pd.DataFrame, bench: pd.Series | None = None) -> dict:
        r = eq["ret"]
        n_years = len(eq) / 252.0
        total = eq["equity"].iloc[-1] / self.init_cash - 1
        cagr = (1 + total) ** (1 / n_years) - 1 if n_years > 0 else np.nan
        dd = eq["equity"] / eq["equity"].cummax() - 1
        vol = r.std() * np.sqrt(252)
        sharpe = (r.mean() * 252 - 0.02) / vol if vol > 0 else np.nan
        downside = r[r < 0].std() * np.sqrt(252)
        monthly = eq["equity"].resample("ME").last().pct_change().dropna()

        sells = [t for t in self.trades if t.side == "sell"]
        buys_by_code: dict[str, list[Trade]] = {}
        for t in self.trades:
            buys_by_code.setdefault(t.code, []).append(t)
        wins, pnl = 0, []
        for t in sells:
            hist = buys_by_code[t.code]
            idx = hist.index(t)
            prev_buy = next((h for h in reversed(hist[:idx]) if h.side == "buy"), None)
            if prev_buy:
                ret = t.price / prev_buy.price - 1
                pnl.append(ret)
                wins += ret > 0

        out = {
            "起始日": eq.index[0].date(),
            "结束日": eq.index[-1].date(),
            "年数": round(n_years, 2),
            "总收益": total,
            "年化收益": cagr,
            "年化波动": vol,
            "夏普(rf=2%)": sharpe,
            "索提诺": (r.mean() * 252 - 0.02) / downside if downside > 0 else np.nan,
            "最大回撤": dd.min(),
            "卡玛比率": cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
            "月胜率": (monthly > 0).mean(),
            "最好月份": monthly.max(),
            "最差月份": monthly.min(),
            "月收益中位数": monthly.median(),
            "交易笔数": len(self.trades),
            "个股胜率": wins / len(pnl) if pnl else np.nan,
            "单笔平均收益": float(np.mean(pnl)) if pnl else np.nan,
            "总费用": sum(t.fee for t in self.trades),
            "持仓天数占比": float((eq["equity"] > 0).mean()),
        }
        if bench is not None:
            b = bench.reindex(eq.index).ffill()
            b_total = b.iloc[-1] / b.iloc[0] - 1
            out["基准总收益(沪深300)"] = b_total
            out["基准年化"] = (1 + b_total) ** (1 / n_years) - 1
            out["基准最大回撤"] = float((b / b.cummax() - 1).min())
        return out
