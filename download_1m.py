"""Download 1-minute klines (open/high/low/close) for the latency test.

Output: data/<SYMBOL>_1m.pkl covering the backtest window.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from download_data import BASE, END, OUT, SYMBOLS, fetch, strip_header

START_1M = pd.Timestamp("2022-11-01")


def klines_1m(sym):
    months = pd.period_range(START_1M, END, freq="M")
    urls = {m: f"{BASE}/monthly/klines/{sym}/1m/{sym}-1m-{m}.zip" for m in months}
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(urls, ex.map(fetch, urls.values())))
    parts = [strip_header(d).iloc[:, :5] for d in res.values() if d is not None]
    for m in [m for m, d in res.items() if d is None]:      # month not published yet -> daily archives
        days = pd.date_range(m.start_time, min(m.end_time, END), freq="D")
        durls = [f"{BASE}/daily/klines/{sym}/1m/{sym}-1m-{d:%Y-%m-%d}.zip" for d in days]
        with ThreadPoolExecutor(8) as ex:
            got = [strip_header(d).iloc[:, :5] for d in ex.map(fetch, durls) if d is not None]
        print(f"  {sym} {m}: monthly missing, {len(got)}/{len(days)} daily files found")
        parts += got
    df = pd.concat(parts, ignore_index=True)
    df.columns = ["open_time", "open", "high", "low", "close"]
    df = df.astype({"open_time": "int64", "open": "float64", "high": "float64", "low": "float64", "close": "float64"})
    df.loc[df.open_time > 10**14, "open_time"] //= 1000
    df["ts"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
    return df.drop_duplicates("ts").sort_values("ts").set_index("ts")[["open", "high", "low", "close"]]


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in SYMBOLS:
        k = klines_1m(s)
        k.to_pickle(f"{OUT}/{s}_1m.pkl")
        print(s, "1m klines", len(k), k.index[0], "->", k.index[-1])
