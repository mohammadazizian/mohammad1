# Exchange announcement poller

Checks Binance, Upbit, Bithumb, and Coinbase public announcements about every 5 minutes. New items are appended to a queue and POSTed to a webhook as JSON: `{ "source": "exchange_poller", "count": N, "items": [ ... ] }` with `Authorization: Bearer <key>`. The program is Python 3 standard library only.

GitHub Actions runs `python3 exchange_poller/poller.py --once` (one pass, then exit). In that mode a new item is posted on the same run. If the webhook is not configured, the job still succeeds and the heartbeat records `webhook: not_configured`. Up to 50 pending items are kept and sent on a later run once the secrets exist.

## Secrets

Add both repository secrets. The poller never prints the URL or the key.

1. Open **Settings > Secrets and variables > Actions > New repository secret**.
2. Create `EXCHANGE_WEBHOOK_URL` (the URL to POST).
3. Create `EXCHANGE_WEBHOOK_KEY` (the bearer token).

## Where data lives

Code is on `master`. Runtime data is on the orphan branch `poller-data`:

- `state.json` — ids already seen, so old announcements are not posted again
- `exchange_queue.jsonl` — append-only queue, one JSON object per line
- `heartbeat.json` — last run UTC, per-source ok/error/count, new item count, webhook status

`state.json` and the queue are committed only when there is a new item or the state changed. A heartbeat-only update is committed at most once every 30 minutes.

## Schedule

`.github/workflows/exchange-poller.yml` is triggered by `cron: */5 * * * *` and by **workflow_dispatch**. GitHub may delay scheduled runs, and it disables schedules after 60 days of no repository activity. The workflow runs from the default branch only, so it starts after this change is merged to `master` and Actions is enabled for the repository.
