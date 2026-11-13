"""Download Binance USDT-M 15m klines + funding rates from data.binance.vision.

Monthly archives are used where they exist; the current (unfinished) month is
filled from daily kline archives.  Output: data/<SYMBOL>_15m.pkl and
data/<SYMBOL>_funding.pkl (raw, un-aligned).
"""
import io
import os
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
START = pd.Timestamp("2022-09-01")
END = pd.Timestamp("2026-11-13")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
         "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def fetch(url):
    """Return list of CSV rows (as DataFrame) or None when the archive does not exist."""
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            return pd.read_csv(z.open(z.namelist()[0]), header=None, low_memory=False)
        except Exception as e:  # network hiccup -> retry
            err = e
    raise RuntimeError(f"failed {url}: {err}")


def strip_header(df):
    if isinstance(df.iloc[0, 0], str) and not df.iloc[0, 0].lstrip("-").isdigit():
        df = df.iloc[1:]
    return df.reset_index(drop=True)


def klines(sym):
    months = pd.period_range(START, END, freq="M")
    urls = {m: f"{BASE}/monthly/klines/{sym}/15m/{sym}-15m-{m}.zip" for m in months}
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(urls, ex.map(fetch, urls.values())))
    parts, missing = [], [m for m, d in res.items() if d is None]
    parts += [strip_header(d) for d in res.values() if d is not None]
    for m in missing:  # month not published yet -> daily archives
        days = pd.date_range(max(m.start_time, START), min(m.end_time, END), freq="D")
        durls = [f"{BASE}/daily/klines/{sym}/15m/{sym}-15m-{d:%Y-%m-%d}.zip" for d in days]
        with ThreadPoolExecutor(8) as ex:
            dres = list(ex.map(fetch, durls))
        got = [strip_header(d) for d in dres if d is not None]
        print(f"  {sym} {m}: monthly missing, {len(got)}/{len(days)} daily files found")
        parts += got
    df = pd.concat(parts, ignore_index=True).iloc[:, :12]
    df.columns = KCOLS
    df = df.astype({c: "float64" for c in KCOLS if c not in ("open_time", "close_time", "count", "ignore")})
    df["open_time"] = df["open_time"].astype("int64")
    df.loc[df.open_time > 10**14, "open_time"] //= 1000  # guard: microsecond stamps
    df["count"] = df["count"].astype("int64")
    df["ts"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
    df = df.drop_duplicates("ts").sort_values("ts").set_index("ts")
    return df[["open", "high", "low", "close", "volume", "quote_volume", "count", "taker_buy_volume"]]


def funding(sym):
    months = pd.period_range(START, END, freq="M")
    urls = [f"{BASE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip" for m in months]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(fetch, urls))
    miss = [str(m) for m, d in zip(months, res) if d is None]
    if miss:
        print(f"  {sym} funding: no archive for {miss}")
    df = pd.concat([strip_header(d) for d in res if d is not None], ignore_index=True).iloc[:, :3]
    df.columns = ["calc_time", "interval_hours", "rate"]
    df["calc_time"] = df["calc_time"].astype("int64")
    df["rate"] = df["rate"].astype("float64")
    df["ts"] = pd.to_datetime(df.calc_time, unit="ms", utc=True)
    return df.drop_duplicates("calc_time").sort_values("ts")[["ts", "rate"]].reset_index(drop=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in SYMBOLS:
        k = klines(s)
        f = funding(s)
        k.to_pickle(f"{OUT}/{s}_15m.pkl")
        f.to_pickle(f"{OUT}/{s}_funding.pkl")
        print(s, "klines", len(k), k.index[0], "->", k.index[-1],
              "| funding", len(f), f.ts.iloc[0], "->", f.ts.iloc[-1])
    sys.exit(0)
