"""A 股日线数据层：腾讯行情接口 + 新浪快照，本地 parquet 缓存。

只依赖公开免费接口，无需 token。数据为前复权（qfq）日线。
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from datetime import date, datetime

import pandas as pd
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
STOCK_DIR = os.path.join(CACHE_DIR, "stocks")
os.makedirs(STOCK_DIR, exist_ok=True)

KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SINA_LIST_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)
SINA_KLINE_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
}
MAX_BARS_PER_REQUEST = 800


def tencent_symbol(code: str) -> str:
    """6 位代码 -> 腾讯行情代码，例如 600519 -> sh600519。"""
    if code.startswith(("5", "6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


_RATE_LOCK = Lock()
_LAST_CALL = [0.0]
MIN_INTERVAL = float(os.environ.get("AQ_MIN_INTERVAL", "1.0"))  # 全局限速，过快会被封 IP


def _throttle() -> None:
    with _RATE_LOCK:
        wait = MIN_INTERVAL - (time.time() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.time()


def _get(url: str, params: dict | None = None, retries: int = 5) -> requests.Response:
    last = None
    for i in range(retries):
        _throttle()
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code in (456, 501, 429, 403):
                raise RuntimeError(f"限流 {r.status_code}")
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001 - 免费接口不稳定，退避重试
            last = exc
            time.sleep(2.0 * (i + 1))
    raise RuntimeError(f"请求失败 {url} {params}: {last}")


def _get_json(url: str, params: dict | None = None, retries: int = 5) -> dict:
    return json.loads(_get(url, params, retries).text)


SINA_HFQ_URL = "https://finance.sina.com.cn/realstock/company/{symbol}/hfq.js"


def _sina_adj_factor(symbol: str) -> pd.Series:
    """新浪后复权因子（按公告日阶梯），索引为生效日。"""
    r = _get(SINA_HFQ_URL.format(symbol=symbol))
    body = r.text.split("=", 1)[1]
    payload = json.loads(body[body.index("{"): body.rindex("}") + 1])
    rows = payload.get("data") or []
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series(
        {pd.Timestamp(x["d"]): float(x["f"]) for x in rows}
    ).sort_index()
    return s


def _fetch_sina(symbol: str, datalen: int = 3000) -> pd.DataFrame:
    """新浪日线（腾讯接口被限流时的备用源），单次最多约 3000 根。

    新浪返回的是未复权价，这里用后复权因子转成与腾讯一致的前复权序列。
    """
    data = _get_json(SINA_KLINE_URL, {"symbol": symbol, "scale": 240, "ma": "no", "datalen": datalen})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data).rename(columns={"day": "date"})
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df["volume"] = df["volume"] / 100.0  # 新浪单位为股，统一成手

    try:
        factors = _sina_adj_factor(symbol)
    except Exception:  # noqa: BLE001 - 拿不到因子就退回未复权
        factors = pd.Series(dtype=float)
    if not factors.empty:
        f = factors.reindex(df["date"], method="ffill").bfill().to_numpy()
        f = f / factors.iloc[-1]
        for col in ["open", "high", "low", "close"]:
            df[col] = (df[col].to_numpy() * f).round(4)
    return df[["date", "open", "high", "low", "close", "volume"]]


def fetch_snapshot(force: bool = False) -> pd.DataFrame:
    """全市场快照：代码、名称、最新价、总市值、流通市值、PE、PB。"""
    path = os.path.join(CACHE_DIR, "snapshot.parquet")
    if os.path.exists(path) and not force:
        return pd.read_parquet(path)

    rows: list[dict] = []
    page = 1
    while True:
        data = _get_json(
            SINA_LIST_URL,
            {"page": page, "num": 100, "sort": "symbol", "asc": 1, "node": "hs_a"},
        )
        if not data:
            break
        rows.extend(data)
        page += 1
        if page > 80:
            break
    df = pd.DataFrame(rows)
    df = df[["code", "name", "trade", "mktcap", "nmc", "per", "pb", "amount"]]
    for col in ["trade", "mktcap", "nmc", "per", "pb", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.to_parquet(path)
    return df


def build_universe(top_n: int = 500, force: bool = False) -> pd.DataFrame:
    """构造股票池：剔除 ST / 退市 / 北交所 / 科创板，按流通市值取前 top_n。

    注意：股票池取自当前上市清单，存在幸存者偏差（已退市个股不在其中），
    回测结果因此偏乐观，README 中有说明。
    """
    snap = fetch_snapshot(force=force)
    snap = snap[~snap["name"].str.contains("ST|退", na=False)]
    snap = snap[~snap["code"].str.startswith(("4", "8", "9", "688"))]
    snap = snap.sort_values("nmc", ascending=False).head(top_n).reset_index(drop=True)
    return snap[["code", "name", "nmc"]]


def _fetch_one(code: str, start: str, end: str, source: str = "sina") -> pd.DataFrame:
    """单只股票的前复权日线。

    source="sina"：未复权价 × 后复权因子，乘法复权，历史价格恒为正——默认。
    source="tencent"：腾讯 qfq，采用除权差价（减法）复权，长历史高分红股会出现负价，仅作备用。
    """
    sym = tencent_symbol(code)
    if source == "sina":
        df = _fetch_sina(sym)
        if df.empty:
            return df
        df["code"] = code
        return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)

    frames: list[pd.DataFrame] = []
    cur_end = end
    while True:
        try:
            data = _get_json(
                KLINE_URL,
                {"param": f"{sym},day,{start},{cur_end},{MAX_BARS_PER_REQUEST},qfq"},
            )
        except RuntimeError:
            if frames:
                break
            return _fetch_sina(sym).assign(code=code).pipe(
                lambda d: d[(d["date"] >= start) & (d["date"] <= end)].reset_index(drop=True)
            )
        payload = data.get("data") or {}
        node = payload.get(sym) or {}
        bars = node.get("qfqday") or node.get("day") or []
        if not bars:
            break
        chunk = pd.DataFrame(
            [b[:6] for b in bars],
            columns=["date", "open", "close", "high", "low", "volume"],
        )
        frames.append(chunk)
        first = chunk["date"].iloc[0]
        if first <= start or len(bars) < MAX_BARS_PER_REQUEST:
            break
        cur_end = (pd.Timestamp(first) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if cur_end <= start:
            break
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).drop_duplicates("date").sort_values("date")
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df["code"] = code
    return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)


def fetch_daily(
    codes: list[str],
    start: str = "2015-01-01",
    end: str | None = None,
    workers: int = 8,
    force: bool = False,
    source: str = "sina",
) -> pd.DataFrame:
    """批量抓取日线，长表格式：date, code, open, high, low, close, volume。

    每只股票单独落盘缓存，被限流中断后重跑可断点续传。
    """
    end = end or date.today().strftime("%Y-%m-%d")
    done = 0
    total = len(codes)

    def job(code: str) -> pd.DataFrame:
        nonlocal done
        cache = os.path.join(STOCK_DIR, f"{source}_{code}.parquet")
        if os.path.exists(cache) and not force:
            out = pd.read_parquet(cache)
        else:
            try:
                out = _fetch_one(code, "1990-01-01", end, source=source)
                if not out.empty:
                    out.to_parquet(cache)
            except Exception as exc:  # noqa: BLE001
                print(f"  跳过 {code}: {exc}", flush=True)
                out = pd.DataFrame()
        done += 1
        if done % 100 == 0:
            print(f"  已处理 {done}/{total}", flush=True)
        if out.empty:
            return out
        return out[(out["date"] >= start) & (out["date"] <= end)]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = [f for f in pool.map(job, codes) if not f.empty]

    if not frames:
        raise RuntimeError("没有抓到任何行情，检查网络或接口限流")
    return pd.concat(frames).sort_values(["date", "code"]).reset_index(drop=True)


def fetch_index(code: str = "sh000300", start: str = "2015-01-01", end: str | None = None) -> pd.DataFrame:
    """指数日线，用于大盘择时与基准对比。"""
    end = end or date.today().strftime("%Y-%m-%d")
    path = os.path.join(CACHE_DIR, f"index_{code}_{start}_{end}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)

    df = _fetch_sina(code)  # 指数无需复权，新浪单次即可取到 3000 根
    if not df.empty:
        df = df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
        df.to_parquet(path)
        return df

    frames: list[pd.DataFrame] = []
    cur_end = end
    try:
        while True:
            data = _get_json(KLINE_URL, {"param": f"{code},day,{start},{cur_end},{MAX_BARS_PER_REQUEST},qfq"})
            node = (data.get("data") or {}).get(code) or {}
            bars = node.get("day") or node.get("qfqday") or []
            if not bars:
                break
            chunk = pd.DataFrame(
                [b[:6] for b in bars],
                columns=["date", "open", "close", "high", "low", "volume"],
            )
            frames.append(chunk)
            first = chunk["date"].iloc[0]
            if first <= start or len(bars) < MAX_BARS_PER_REQUEST:
                break
            cur_end = (pd.Timestamp(first) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            if cur_end <= start:
                break
    except RuntimeError:
        frames = []

    if frames:
        df = pd.concat(frames).drop_duplicates("date").sort_values("date")
        for col in ["open", "close", "high", "low", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
    else:
        df = _fetch_sina(code)
    df = df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
    df.to_parquet(path)
    return df


def to_panel(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """长表转宽表面板：{field: DataFrame(index=date, columns=code)}。"""
    panel = {}
    for field in ["open", "high", "low", "close", "volume"]:
        panel[field] = df.pivot(index="date", columns="code", values=field).sort_index()
    return panel


if __name__ == "__main__":
    uni = build_universe(20)
    print(uni.head())
    px = fetch_daily(uni["code"].tolist()[:3], start="2024-01-01")
    print(px.tail())
    print(datetime.now())
