# Three 15m strategies for BTC & ETH perpetuals

| | Strategy 1 - session fades (`strategy.py`) | Strategy 2 - shock & flow momentum (`strategy2.py`) |
|---|---|---|
| Required window 2024-11 -> 2026-11, profitable months | BTC 22/25, ETH 21/25 | BTC 20/25, ETH 21/25 |
| Required window, net PnL | BTC +76.9 %, ETH +94.9 % | BTC +39.5 %, ETH +81.3 % |
| Holdout 2022-11 -> 2024-11, profitable months | BTC 16/25, ETH 17/25 | BTC 21/25, ETH 20/25 |
| Holdout, net PnL | BTC -62.9 %, ETH +14.2 % | BTC +53.1 %, ETH +64.5 % |

**Strategy 1 fails on the earlier two years; Strategy 2 holds up on them.** Prefer Strategy 2.

# Strategy 3 - Large-Trade ("Whale") Momentum + Monthly Governor (`strategy3.py`)

| | BTCUSDT | ETHUSDT |
|---|---|---|
| Required window 2024-11 -> 2026-11: profitable months / net PnL | 21/25, +35.1 % | 20/25, +35.2 % |
| Holdout 2022-11 -> 2024-11: profitable months / net PnL | 20/25, +27.2 % | 20/25, +8.0 % |

* Average trade size = quote volume / number of trades, summed over the last 4 bars (1 h). z-score it against its own 7-day mean/std.
* When z > 2 (first bar it becomes true or the direction flips): go LONG if close > close 4 bars ago, SHORT if lower. Entry at next bar open.
* Exit 96 bars (24 h) after entry, or at a stop 4 x ATR(96, Wilder) from entry (stop has priority inside a bar).
* Size = equity x min(1.0, 2 % / daily sigma). One position at a time.
* Monthly governor at +1 % of equity. Same costs as the other strategies.

Caveats: the monthly count is stable across neighbours, the profit is not. On BTC, z thresholds of 2.25/2.5 or look-backs of 3/8 bars turn net PnL negative in one or both periods (`results/s3_sensitivity.txt`). Without the governor: 13-18 of 25 months, still net positive in all four cells. ETH holdout profit (+8 %) is thin. Treat this as the weakest of the two validated strategies.

# Strategy 2 - Shock & Flow Momentum + Monthly Governor

Same data, costs and execution conventions as Strategy 1 (0.04 % fee + 0.01 % slippage per side, funding included, entries at next bar open).
`sigma` = std-dev of 15m log returns over 7 days (672 bars).

| Sleeve | Signal (checked every bar close) | Direction | Exit |
|---|---|---|---|
| S - shock momentum | last 1 h log return / (sigma*sqrt(4)) beyond +-4 | with the move | 48 bars (12 h) after entry |
| F - flow momentum | 4 h sum of (taker buy volume - taker sell volume), z-scored against its own 7-day mean/std, beyond +-3 | with the flow | 48 bars (12 h) after entry |

* Size per sleeve: notional = equity x min(1.0, 2 % / daily sigma); one position per sleeve; a sleeve re-enters only after its trade has closed.
* Monthly governor: after realised calendar-month PnL reaches +1 % of equity (and at least one trade was opened), no new entries until next month.
* No stop loss.

Caveats:
* Without the governor the same signals are profitable in all four coin/period cells (+29 % to +151 %) but only 15-17 of 25 months are green. The governor is what lifts the count to 80 %+, by giving up upside.
* BTC sits exactly on 80 % (20/25) in the required window; neighbours such as shock threshold 3.5 or flow threshold 2.75 give 17/25. Net PnL stays positive in every variant tested on both periods (`results/s2_sensitivity.txt`).
* The +1 % target was picked from a 0.75-1.5 % plateau after seeing the holdout, so the holdout is not perfectly clean for that one parameter.
* Worst months: -9.5 % BTC, -15.6 % ETH.

# Strategy 1 - Session-Reversion Ensemble + Monthly Governor

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
* **Fails out of sample.** On 2022-11 -> 2024-11 it gives BTC 16/25 months and -62.9 %, ETH 17/25 and +14.2 % (`results/s1_holdout.txt`); without the governor both coins lose.
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
