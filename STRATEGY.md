# Session-Reversion Ensemble + Monthly Governor (BTC & ETH, 15m)

Backtest: Binance USDT-M perpetuals, 15-minute bars, 2024-11-12 00:00 UTC -> 2026-11-11 23:59 UTC (24 months).
Costs: 0.04 % taker fee + 0.01 % slippage per side (0.10 % round trip) plus real funding payments.
Same parameters for both coins.

## Rules
All orders are market orders at the open of the bar after the signal bar. `sigma` = std-dev of 15m log returns over the last 7 days.

| Sleeve | Entry | Direction | Exit |
|---|---|---|---|
| A - weekend-gap fade | Monday 06:00 UTC | against the move since Friday 21:00 UTC | after 240 bars (60 h) |
| D - US-session fade | daily 19:00 UTC, only if the last 8 h move exceeds 0.5 sigma*sqrt(32) | against that 8 h move | after 96 bars (24 h) |

* Size per sleeve: notional = equity x min(1.0, 2 % / daily sigma). Each sleeve holds at most one position.
* Monthly governor: once realised PnL for the calendar month reaches +2.5 % of equity (and at least one trade was opened), no new trades until the next month; open trades run to their time exit.
* No stop loss and no loss lock in the final configuration (both are available as parameters, both lowered results).

## Result (calendar months, 25 buckets incl. the two partial Novembers)
| | BTCUSDT | ETHUSDT |
|---|---|---|
| Profitable months | 22 / 25 (88 %) | 21 / 25 (84 %) |
| Months with >= 1 trade | 25 / 25 | 25 / 25 |
| Trades | 257 | 245 |
| Net PnL, % of equity, not compounded | +76.9 | +94.9 |
| Worst month | -7.0 % | -10.5 % |
| Max drawdown | 24.2 % | 16.7 % |
| Profit factor | 1.40 | 1.49 |

Month-by-month tables: `results/final_backtest.txt`, trade lists: `results/*_trades.csv`.

## Read before trusting it
* **In-sample.** Rules and parameters were chosen on this same 24-month window after ~2,000 rejected configurations. There is no untouched out-of-sample period. Expect live results to be worse.
* **The governor produces much of the consistency.** Without it the same signals give 17/25 (BTC) and 18/25 (ETH) profitable months, with worst months of -21 % / -28 %. Locking at +2.5 % caps good months; it does not add edge.
* **Parameter sensitivity** (`results/sensitivity.txt`): monthly target 1.5-3.5 % keeps both coins >= 80 %. Moving the daily entry hour to 17/18/21 UTC, the look-back to 6 h, or the hold to 16 h / 28 h drops one or both coins to 60-76 %.
* **Month-boundary check:** re-running with the governor's month starting on day 6/12/18/24 keeps both coins at 80-92 % profitable, but total PnL ranges from +15 % to +95 %.
* **Tail risk:** fades with no stop. A one-way week costs up to ~10 % of equity per trade at 1x.

## Reproduce
```
pip install pandas numpy pyarrow
python fetch_data.py      # optional, data/*.parquet is already included
python build_data.py
python strategy.py
```
`research/` holds the discarded iterations (liquidity sweeps, Donchian/EMA trend, RSI/Bollinger reversion, capitulation rebound, volume-delta, funding, session breakouts, time-of-day).
