"""Download Binance USDT-M 5m klines + funding (public archive) into raw5/, then build data/*.parquet.
BTC/ETH from 2020-01, SOL from 2020-09, seven more coins from 2022-06.   python fetch_data.py"""
import os, urllib.request, pandas as pd, build_data as BD
B = "https://data.binance.vision/data/futures/um"
COINS = [("BTCUSDT", "2020-01"), ("ETHUSDT", "2020-01"), ("SOLUSDT", "2020-09")] + [(c, "2022-06") for c in
         ["BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]]
def get(url):
    dst = os.path.join("raw5", os.path.basename(url))
    if not os.path.exists(dst):
        try: urllib.request.urlretrieve(url, dst)
        except Exception: pass
if __name__ == "__main__":
    os.makedirs("raw5", exist_ok=True); os.makedirs("data", exist_ok=True)
    for s, a in COINS:
        for m in pd.period_range(a, "2026-10", freq="M"):
            get(f"{B}/monthly/klines/{s}/5m/{s}-5m-{m}.zip"); get(f"{B}/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip")
        for d in range(1, 12): get(f"{B}/daily/klines/{s}/5m/{s}-5m-2026-11-{d:02d}.zip")
        BD.load(s, raw="raw5").to_parquet(f"data/{s}_5m.parquet"); print("built", s)
