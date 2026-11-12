"""Download Binance USDT-M perpetual 5m klines + funding history (public archive) into data/raw/."""
import os, sys, urllib.request, datetime as dt
BASE = os.environ.get("BINANCE_ARCHIVE", "https://data.binance.vision") + "/data/futures/um"
def months(a, b):
    y, m = a
    while (y, m) <= b:
        yield f"{y}-{m:02d}"; m += 1
        if m == 13: y, m = y + 1, 1
def get(url, dst):
    if os.path.exists(dst): return
    try: urllib.request.urlretrieve(url, dst)
    except Exception as e: print("skip", url, e)
if __name__ == "__main__":
    os.makedirs("data/raw", exist_ok=True)
    for s in ["BTCUSDT", "ETHUSDT"]:
        for ym in months((2024, 9), (2026, 10)):
            get(f"{BASE}/monthly/klines/{s}/5m/{s}-5m-{ym}.zip", f"data/raw/{s}-5m-{ym}.zip")
            get(f"{BASE}/monthly/fundingRate/{s}/{s}-fundingRate-{ym}.zip", f"data/raw/{s}-fundingRate-{ym}.zip")
        for day in range(1, 12):
            get(f"{BASE}/daily/klines/{s}/5m/{s}-5m-2026-11-{day:02d}.zip", f"data/raw/{s}-5m-2026-11-{day:02d}.zip")
    print("done - now run: python build_data.py && python strategy.py")
