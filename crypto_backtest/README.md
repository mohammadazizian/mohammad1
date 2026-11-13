# BTC / ETH 1H momentum-burst strategy with a monthly profit lock

`strategy.py` is self-contained (pandas + numpy): it downloads Binance spot 1H candles
(REST API, falling back to the `finom/static-klines` GitHub mirror), runs the backtest and prints
the month-by-month table. `python strategy.py --out results`

## Rules (1H candles, identical parameters for BTC and ETH)

Each asset account is split 50/50 between two independent sleeves. Signals are evaluated on a closed
bar and executed at the next bar's open.

| | Sleeve A – Bollinger breakout | Sleeve B – impulse bar |
|---|---|---|
| Long | z = (close − SMA20) / STD20 crosses above **+2.5** | 1H log-return / 480-bar return-σ **> +3.0** and close in top 40% of the bar |
| Short | z crosses below **−2.5** | return/σ **< −3.0** and close in bottom 40% of the bar |
| Exit | time stop after **48 bars** | take-profit limit at **2.0 × ATR(24)** or time stop after **48 bars** |

**Monthly governor:** once the account's mark-to-market month-to-date PnL reaches **+2.0%** (and at
least one trade was opened that month), everything is closed at the next open and trading stops
until the 1st of the next month.

**Costs:** taker 0.04% + 0.02% slippage per side on every market fill (12 bps round trip);
maker 0.01% on take-profit limits, which only fill if price trades 1 bp through the level.
Fixed notional, no leverage, no compounding.

## Result: Nov 2024 – Oct 2026 (24 calendar months, net of costs)

| | BTC | ETH |
|---|---|---|
| Profitable months | **21 / 24 (87.5%)** | **22 / 24 (91.7%)** |
| Months with ≥ 1 trade | 24 / 24 | 24 / 24 |
| Total net PnL (1x notional) | +38.6% | +38.5% |
| Worst month / max drawdown | −7.1% / −13.0% | −11.5% / −15.3% |
| Trades / trade win-rate | 163 / 68% | 112 / 71% |
| Avg net profit per trade | 47 bps | 69 bps |

Full tables: `results/backtest_output.txt`, `results/*_monthly.csv`, `results/*_trades.csv`.

With months counted from the 13th instead (13 Nov 2024 → 12 Nov 2026, `--anchor-day 13`):
BTC 22/24, ETH 21/24.

## Follow-up tests: regime filters and walk-forward

**Regime filters** (base parameters, profit lock on; `--trend-filter` enables the first one):

| Filter | BTC 2022-03..2024-10 | BTC 2024-11..2026-10 | ETH 2022-03..2024-10 | ETH 2024-11..2026-10 |
|---|---|---|---|---|
| none (default) | 22/32, −2.7%, DD −23% | 21/24, +38.6%, DD −13% | 26/32, +8.2%, DD −32% | 22/24, +38.5%, DD −15% |
| trend: longs above / shorts below SMA720 | 22/32, +9.9%, DD −18% | 20/24, +35.4%, DD −9% | 27/32, +44.1%, DD −13% | 17/24, +17.3%, DD −15% |
| entries 00–12 UTC only | 21/32, −0.2% | 15/24, +12.4% | 26/32, +24.8% | 19/24, +19.0% |

No filter improved both periods on both assets. The trend filter lowers drawdowns and helps
2022–24, but halves ETH's 2024–26 profit and leaves it at 17/24. It is available as an option and
is off by default. Volatility level, efficiency ratio and volume regime showed no consistent
relationship with trade outcomes.

**Walk-forward** (`walkforward.py`): parameters and filter are re-selected from the preceding
training window only, then traded on the following months, so every traded month is out-of-sample.
Results for Nov 2024 – Oct 2026 with the 2% profit lock:

| Training / re-selection | BTC | ETH |
|---|---|---|
| 24 months / 6 months | 15/24, +13.8% | 20/24, +19.8% |
| 18 months / 6 months | 16/24, +14.7% | 20/24, +14.5% |
| 12 months / 3 months | 14/24, −7.8% | 17/24, −13.4% |

Full tables: `results/walkforward_*.txt`. The fixed-parameter backtest above (+38.6% / +38.5%,
21/24 and 22/24) is therefore optimistic: with honest re-selection roughly a third to a half of the
profit survives when training windows are 18–24 months, BTC falls below the 70% line, and a
12-month window is too short to select parameters reliably.

## Read this before trading it

* **The profit lock shapes the distribution; it does not create edge.** It turns the PnL into many
  ≈ +2% months and a few larger losing months (−7% to −11%). Without it (`--no-governor`) the same
  entries made more money (BTC +69.7%, ETH +96.4%) with 19/24 and 18/24 profitable months.
* **Out-of-sample check, Feb 2022 – Oct 2024** (not used for tuning): BTC 23/33 profitable months
  (69.7%) but only +0.1% total; ETH 27/33 (81.8%), +10.4% total. The monthly consistency carried
  over; the profit mostly did not. The entry edge was weak in 2022–24 and the entry parameters were
  selected on the 2024–26 window, so expect live results below the backtest.
* Parameter sensitivity: with the governor on, every single-parameter variation tested (SMA length
  14–30, k 2.0–3.0, holds 12–96 bars, impulse 2.5–4σ, TP 1–3 ATR, lock 1–5%) kept both assets at
  ≥ 17/24 profitable months. Without the governor the 70% line is not robust to those changes.
* Cost stress (0.05% taker + 0.05% slippage per side): BTC 20/24, ETH 22/24.
* Timeframe: the same logic on 30m and 15m candles had an average trade of 7–15 bps (BTC negative
  on 15m), too close to the 12 bps round-trip cost, so 1H is the lowest timeframe that survives fees.
  5m data was not available in the research environment and was not tested.
* Prices are Binance **spot** candles; shorting needs perpetual futures, and funding payments are
  not modelled.
