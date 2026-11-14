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
| 12 months / 3 months | 14/24, −6.4% | 17/24, −13.4% |

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

---

# Volume-Delta Burst (volume-only trigger, fixed SL/TP) — `volume_strategy.py`

`python volume_strategy.py --out results_volume`

## Rules (1H candles, identical for BTC and ETH)

* **Trigger:** `delta` = taker-buy volume − taker-sell volume per bar. `burst` = sum of `delta`
  over the last 2 bars, z-scored against its own last 336 bars. Long when z crosses above **+2.5**,
  short when it crosses below **−2.5**. Entry is a market order at the next bar's open.
* **Fixed exits, set at entry and never moved:** stop loss **6.0 × ATR(24)**, take profit
  **4.0 × ATR(24)**. No other exit exists. One position per asset.
* **Monthly entry lock:** once mark-to-market month-to-date PnL reaches **+1.0%**, no new trade is
  opened until the next calendar month. Open trades still end only at their SL or TP.
* **Costs:** taker 0.04% + 0.02% slippage on entries and stops; maker 0.01% on take-profits (filled
  only if price trades 1 bp through). If SL and TP fall inside one bar the SL is assumed first.

## Result: Nov 2024 – Oct 2026 (24 calendar months, net of costs)

| | BTC | ETH |
|---|---|---|
| Profitable months | **20 / 24 (83.3%)** | **22 / 24 (91.7%)** |
| Months with ≥ 1 trade | 24 / 24 | 24 / 24 |
| Total net PnL (1x notional) | +30.6% | +69.4% |
| Worst month / max drawdown | −7.0% / −22.5% | −10.0% / −18.6% |
| Trades (TP / SL) | 42 (32 / 10) | 36 (29 / 7) |
| Avg SL / TP distance | 4.0% / 2.7% | 6.1% / 4.0% |

Full tables: `results_volume/backtest_output.txt`, `results_volume/*_monthly.csv`,
`results_volume/*_trades.csv` (every trade with its entry, SL, TP and exit type).

## Read this before trading it

* **Tiny sample.** Because the first winning trade usually triggers the lock, most months contain
  exactly one trade: 42 and 36 trades in two years. Twenty winning months is roughly twenty winning
  trades; a few different outcomes would change the headline.
* **BTC sits exactly on the 80% line** (20/24). With months counted from the 13th
  (`--anchor-day 13`) the result is BTC 21/24 and ETH 19/24, i.e. ETH falls just under 80%.
* **The lock produces the consistency.** Without it (`--no-lock`) the same entries made BTC +42.1%
  and ETH +79.5% but with 14/24 and 15/24 profitable months and drawdowns of −39% and −47%.
* **Mar 2022 – Oct 2024:** BTC 25/32 (78%), +30.5%; ETH 27/32 (84%), +24.2%. This period was used
  when choosing the signal family, so it is a consistency check, not a clean out-of-sample test.
* **Walk-forward of the family** (delta window, threshold, SL and TP re-selected from the previous
  12–24 months only, 1% lock): BTC 16–19 of 24 profitable months (−12% to +26% total), ETH 17–18 of
  24 (+20% to +34%). Under honest re-selection the strategy does not reach 80%.
* **Neighbouring parameters** with the lock give BTC 18–23 and ETH 19–23 profitable months, so the
  80% line is met by some neighbours and missed by others.
* **Risk shape:** the stop is 1.5× the target, so one stop-out erases about one and a half winners;
  the worst months are single stop-outs.
* **What did not work:** volume-spike reversal, stopping-volume wicks, absorption, CVD divergence
  and volume-confirmed VWAP crosses all lost money after costs with fixed ATR stops (about 2,000
  configurations on 1H). Only following abnormal volume delta with wide stops was positive in every
  sub-period. On 30m the same rule had no edge without the lock.
* Prices and taker-buy volume are Binance **spot**; shorts need perpetual futures and funding is not
  modelled.

---

# Weekend-gap fade + daily US-session fade — `session_fade.py`

Implemented exactly as specified (no rule or parameter changed) on Binance USDT-M perpetual 15m
candles with historical funding, from `data.binance.vision`.
`python session_fade.py --out results_session_fade`

| 2024-11-12 → 2026-11-11, costs + governor | BTC | ETH | Reference BTC / ETH |
|---|---|---|---|
| Trades | 257 | 245 | 257 / 245 |
| Profitable months (of 25) | 22 | 21 | 22 / 21 |
| Total net PnL | +76.9% | +94.8% | +76.9% / +94.9% |
| Worst month | −7.0% | −10.5% | −7.0% / −10.5% |
| Max drawdown | 24.2% | 16.7% | 24.2% / 16.7% |
| Profit factor | 1.40 | 1.49 | 1.40 / 1.49 |

The reference results are reproduced. Zero-cost and governor-off summaries and the monthly tables
are in `results_session_fade/backtest_output.txt`. Funding for November 2026 was not yet published
in the archive and is taken as zero (8 trades per symbol).

Same rules on the preceding two years (`--start 2022-11-12 --end 2024-11-11`,
`results_session_fade/earlier_window_2022-11_2024-11.txt`):

| 2022-11-12 → 2024-11-11, costs + governor | BTC | ETH |
|---|---|---|
| Profitable months (of 25) | 16 | 17 |
| Total net PnL | −63.2% | +14.2% |
| Worst month | −31.0% | −20.9% |
| Max drawdown | 71.5% | 50.4% |
| Profit factor | 0.79 | 1.05 |

The strategy fades moves, and it lost heavily in 2022–24 when BTC trended; its 2024–26 result
depends on that period's mean-reverting behaviour.

---

# Momentum-Shock v2 (redesign against a requirement list) — `strategy_v2.py`

`python strategy_v2.py --out results_v2` (BTC + ETH) · `python strategy_v2.py --all-coins`

Binance USDT-M perpetual 1H candles with real funding, January 2022 – October 2026 (58 months).

**Rules.** Two entry rules, each trading half of one fixed notional:
A) Bollinger z(20) crosses ±2.5 → follow; stop 3×ATR(24), target 6×ATR(24) (1:2).
B) 1H return beyond ±3σ(480) closing in the outer 40% of the bar → follow; stop 3×ATR, target 3×ATR (1:1).
Any trade still open after 48 bars is closed. When month-to-date mark-to-market PnL reaches +2%,
everything is closed and trading stops until the next month.

**How the parameters were chosen.** Stop, targets and lock were picked on pooled results of ten
coins for 2022–2024 only (highest median profit among variants with risk:reward ≥ 1:1 on both rules);
2025–2026 was then used as validation. The entry rules themselves came from the earlier BTC/ETH work.

| Requirement | BTC | ETH |
|---|---|---|
| Trade in every month | yes (min 1) | yes (min 1) |
| ≥ 80% profitable months | 47/58 (81%) | 48/58 (83%) |
| Fixed position size | yes | yes |
| Profitable each year 2023–2026 | +5.4 / +14.0 / +9.7 / +13.2 | **−9.3** / +20.3 / +24.1 / +16.0 |
| Risk:reward | planned 1:2 and 1:1; realised avg win/avg loss 1.27, win rate 49% | 1.23, 48% |
| Total net / max drawdown | +61.9% / −19.5% | +44.3% / **−49.5%** |
| Worst month | −10.6% | −16.2% |

**Ten coins** (`results_v2/all_coins.txt`): 9 of 10 have ≥ 79% profitable months, 7 of 10 are
profitable in total (BNB, XRP and DOGE lose), and only 4 of 10 are profitable in 2026.
Validation period 2025–2026: median coin 86% profitable months, +22%.

**What is not met / weak**
* ETH lost in 2022 and 2023; its drawdown at 1x notional was about half the notional.
* Months are asymmetric: winning months are capped near +2%, losing months reach −10% to −16%.
  A monthly loss cap of −8% (`--loss-cap 0.08`) makes all ten coins profitable in total but drops
  ETH to 45/58 (78%); tighter caps destroy the 80%.
* Without the monthly lock (`--no-lock`) the same entries give 47–48% profitable months and
  BTC −5%, ETH +24%: the lock's profit-taking, not the entry signal, carries the result.
* Other markets: the same rules on Binance's tokenised gold (PAXGUSDT) and EURUSDT pairs lost money
  even at 1 bp cost per side. The logic (drift after price shocks) is a documented effect, but this
  parameterisation is not validated outside crypto.
* The earlier trend-filtered volume-delta design, chosen on 2022–2024 only, made +50.7% in 2025 but
  −14.8% in 2026 (ten-coin average) with 57% profitable months; it was rejected.

`multi_coin_test.py` / `results_multi_coin/` hold the earlier risk-sized ten-coin test of the first
two strategies.

## v2 update: monthly loss cap enabled, 8% target and news filter tested

`strategy_v2.py` now stops for the month at **−10%** as well as at +2% (`--loss-cap 0` turns it off).
The figures in the table above are superseded by these (2022-01 .. 2026-10, 58 months):

| | BTC | ETH |
|---|---|---|
| Profitable months | 47/58 (81%) | 47/58 (81%) |
| Year by year 2022–2026 | +19.6 / +5.4 / +12.5 / +10.2 / +13.2 | +2.9 / **−16.1** / +20.3 / +15.2 / +16.0 |
| Total net / per year | +60.9% / ≈ 12.6% | +38.3% / ≈ 7.9% |
| Worst month / max drawdown | −10.1% / −20.5% | −11.7% / −44.6% |

Ten coins (`results_v2/all_coins.txt`): 8 of 10 reach ≥ 81% profitable months, 8 of 10 are
profitable in total (BNB and DOGE lose), 3 of 10 are profitable in 2026. A −8% cap leaves ETH at 78%.

**8% per month target.** Raising the monthly target to +8% with a −8% cap (same thing as 4x leverage
on a +2% / −2% rule) reaches the target in 20 of 58 months on BTC and 26 of 58 on ETH. A ten-coin
account with a +8% target reaches it in 29 of 58 months with a −8% cap and 40 of 58 with a −16% cap,
with drawdowns of 77% to 135% of the account. The rules do not have enough edge for that target.

**News filter.** Entries near FOMC, CPI and NFP releases (dates hard-coded from memory; CPI only to
September 2025, NFP approximated as first Fridays) showed no stable effect: CPI-window trades
averaged −177 bp in 2022–24 and +104 bp in 2025–26, NFP +107 bp then 0 bp. Blocking entries before
or around the releases changed results within noise, so no news filter was added.

## Search for an 8%-per-month design (not found)

Target: most coins make ≥ 8% in most months with ≥ 80% profitable months. That needs roughly a
Sharpe ratio of 3 at ~100% a year. Tested on ten perpetuals, 2022-01 .. 2026-10
(`research_alt_strategies.py`, output in `results_v2/alt_strategies_vs_8pct_target.txt`):

| Approach | Result |
|---|---|
| Momentum-Shock v2, per coin | Sharpe ≈ 1.25 on the ten-coin average, ≈ 8–13% a year on BTC/ETH |
| Funding carry (long spot / short perp while funding > 0) | 76% profitable months, Sharpe ≈ 2.4, but only ≈ 5% a year; cannot be levered without borrowing at a similar rate |
| Cross-sectional reversal (1–28 days) | loses 3–10% a month |
| Cross-sectional momentum (5–28 days, 54 variants) | Sharpe up to 1.4 on 2022–24, **negative on 2025–26** for nearly every variant |
| Daily trend (SMA 10–100) | Sharpe 0.1–0.4 on the basket, −23% to −42% worst months |
| v2 + cross-sectional momentum, risk-balanced, 5x | 8% reached in 28 of 58 months, worst month −42%, drawdown −91% |
| v2 with +8% target / −8% cap | 8% reached in 20 (BTC) and 26 (ETH) of 58 months |

No strategy or sizing scheme tested reaches the target; leverage only scales losses with gains.

---

# Verification of the other session's strategies 2 and 3 (`s23_verification/`)

Code for strategies 2/3 and the money-management engine (`mm.py`, `bot6.py`, `strategy2.py`,
`strategy3.py`, `build_data.py`) is copied from branch `claude/crypto-trading-backtest-rerxwz`.
New here: `fetch_data.py` (5m data back to 2020 and seven more coins), `oos_test.py`,
`six_year_run.py`, `time_of_day.py`, `time_of_day_adaptive.py`; outputs in `s23_verification/results/`.

**Reproduction.** Strategy 2 and 3 monthly results and the fixed-stop account (x7.41) reproduce exactly.

**"Strict" account** (BTC + ETH shock/flow momentum with 30-day trend and volatility filters, large-trade
momentum on BTC/ETH/SOL, fixed % stops and targets, risk per trade, 3x leverage cap, monthly loss lock):

| | Tuning window 2022-11 → 2026-11 | Untouched 2020-11 → 2022-11 | Six years 2020-11 → 2026-11 |
|---|---|---|---|
| Risk 0.5%: CAGR / max drawdown | 81% / 10.6% | 50% / 14.1% | 70% / 14.1% |
| Risk 0.5%: profitable months | 39/49 | 17/25 | 56/73 (77%), median month +3.9% |
| Risk 1%, lock −10%: CAGR / drawdown | — | — | 146% / 25.7%, 55/73 months, median +6.0%, ≥ 8% in 33/73 |
| Risk 0.5% at 0.20% round-trip cost | — | — | CAGR 45%, 46/73 months |

Every calendar year 2020–2026 is positive (weakest: 2021 +15.7%, 2026 +24.3% at 0.5% risk).
The same rules without the strict filters made −0.6% with a 56% drawdown on 2020–22.

**Does not transfer to other coins.** On BNB, XRP, DOGE, ADA, AVAX, LINK, DOT (never used for tuning,
stops scaled by volatility) one account loses 5% a year with a 50% drawdown; single coins range from
−12% to +9% a year.

**Other weak points.** 46 trades a month, 36% win rate, longest losing streak 23 trades; 58% of exits are
1–1.5% stops filled at the exact stop price in the backtest; results fall quickly with costs.

# Time-of-day study (`time_of_day.py`)

Ten coins, hourly, 2022–2026. Unconditional hour effects are a few basis points (only 13:00 UTC is
negative in all five years, −2.5 to −6 bp) against a 10 bp round-trip cost. Of 1,056 fixed-hour rules
(enter at hour h, hold 1–24 h, long/short, or follow/fade the preceding 4–24 h move), 61 had t > 2 on
2022–24 and none had t > 2 on 2025–26. The strongest pattern, following the day's move in the US evening
(18–23 UTC), was strongly positive in 2022–24 (9–10 of 10 coins) and strongly negative in 2025–26 (0 of
10 coins); a rule that switches between follow and fade using trailing 90–365-day performance was
positive in 13 of 54 variants (`time_of_day_adaptive.py`).
