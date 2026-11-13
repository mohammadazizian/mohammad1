"""Assemble Binance USDT-M perpetual 5m klines (+funding) into one parquet per symbol."""
import glob, zipfile, io, sys
import pandas as pd

COLS = ["open_time","open","high","low","close","volume","close_time","quote_volume",
        "trades","taker_buy_base","taker_buy_quote","ignore"]

def load(sym, raw="data/raw"):
    fs = sorted(glob.glob(f"{raw}/{sym}-5m-*.zip"))
    out = []
    for f in fs:
        with zipfile.ZipFile(f) as z:
            b = z.read(z.namelist()[0])
        df = pd.read_csv(io.BytesIO(b), header=None, names=COLS)
        if not str(df.iloc[0, 0]).isdigit():
            df = df.iloc[1:]
        out.append(df)
    df = pd.concat(out).astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df = df.drop_duplicates("open_time").set_index("open_time").sort_index()
    df = df[["open","high","low","close","volume","quote_volume","trades","taker_buy_base"]]
    fr = []
    for f in sorted(glob.glob(f"{raw}/{sym}-fundingRate-*.zip")):
        with zipfile.ZipFile(f) as z:
            fr.append(pd.read_csv(io.BytesIO(z.read(z.namelist()[0]))))
    fr = pd.concat(fr)
    fr["t"] = pd.to_datetime(fr["calc_time"], unit="ms", utc=True).dt.floor("5min")
    df["funding"] = fr.drop_duplicates("t").set_index("t")["last_funding_rate"].reindex(df.index).fillna(0.0)
    return df

if __name__ == "__main__":
    for s in (sys.argv[1:] or ["BTCUSDT", "ETHUSDT"]):
        d = load(s)
        gaps = (d.index.to_series().diff() != pd.Timedelta("5min")).sum() - 1
        print(s, d.shape, d.index[0], d.index[-1], "gaps:", gaps, "fund events:", (d.funding != 0).sum())
        d.to_parquet(f"data/{s}_5m.parquet")
