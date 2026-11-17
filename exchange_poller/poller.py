#!/usr/bin/env python3
"""Lightweight, model-free poller for Binance, Upbit, Bithumb and Coinbase announcements.

Polls public JSON/RSS/HTML endpoints, dedupes against a state file, and appends
only NEW items to exchange_queue.jsonl. On first start, existing items are
seeded as already seen and are not enqueued.

Daemon mode loops every 2–3 minutes (with jitter). `--once` runs a single
cycle and exits, for GitHub Actions. Data files live in a configurable
directory (``--data-dir`` or ``POLLER_DATA_DIR``).

Never uses an LLM. Never logs secret values (webhook URL or key).
"""

from __future__ import annotations

import argparse
import email.utils
import fcntl
import json
import logging
import os
import queue
import random
import re
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Paths (set by configure_paths; nothing is hard-coded to a machine)
# ---------------------------------------------------------------------------
DATA_DIR = Path("data")
QUEUE_PATH = DATA_DIR / "exchange_queue.jsonl"
CURSOR_PATH = DATA_DIR / "exchange_queue.cursor"
HEARTBEAT_PATH = DATA_DIR / "heartbeat.json"
STATE_PATH = DATA_DIR / "state.json"
LOG_PATH = DATA_DIR / "exchange_poller.log"
PID_PATH = DATA_DIR / "exchange_poller.pid"
LOCK_PATH = DATA_DIR / "exchange_poller.lock"

# Optional env file. On the original box this lived at a fixed path; here it
# is used only when WEBHOOK_ENV_FILE is set or that legacy file exists.
_LEGACY_WEBHOOK_ENV = Path("/home/box/.secrets/exchange_webhook.env")

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
POLL_SECONDS = 150  # 2.5 minutes; jitter makes the actual wait 120–180s
JITTER_SECONDS = 30
HTTP_TIMEOUT = 15
SOURCE_TIMEOUT = 45  # hard cap per source, including all endpoint fallbacks
ONCE_BUDGET_SECONDS = 180  # overall hard cap for a --once run (~3 minutes)
MAX_BODY_BYTES = 2 * 1024 * 1024
WEBHOOK_TIMEOUT = 10
WEBHOOK_MIN_INTERVAL = 300  # daemon mode: at most one POST per 5 minutes
BACKOFF_CAP_SECONDS = 30 * 60
LOG_ROTATE_BYTES = 5 * 1024 * 1024
SEEN_PRUNE_MAX = 4000
SEEN_PRUNE_KEEP = 2500

# Grok Bot routine webhooks: official format is `Authorization: Bearer <key>`.
# If a routine panel shows a different scheme, change these two constants.
WEBHOOK_AUTH_HEADER = "Authorization"
WEBHOOK_AUTH_PREFIX = "Bearer "

# Browser-like UA: Bithumb feed-api and some Cloudflare fronts 403 a
# custom UA but return JSON for a normal Chrome UA.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
KST = ZoneInfo("Asia/Seoul")

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
DELIST_RE = re.compile(
    r"(delist|de-list|removal of (?:spot |margin |futures )?trad|"
    r"will remove|removed from|trading pair.? remov|"
    r"거래지원\s*종료|거래\s*지원\s*종료|상장\s*폐지|거래\s*종료|"
    r"discontinue support|cease support)",
    re.I,
)
LISTING_RE = re.compile(
    r"(will list|lists\b|listing|new cryptocurrency|market support|"
    r"will launch|adds? support for|now available|"
    r"상장|마켓\s*추가|마켓추가|"
    r"거래지원(?!\s*종료)|거래\s*지원(?!\s*종료))",
    re.I,
)
TAG_RE = re.compile(
    r"(seed tag|monitoring tag|caution tag|investment warning|"
    r"watch.?list|innovation zone|"
    r"거래유의|투자\s*유의|유의종목|모니터링\s*태그|시드\s*태그)",
    re.I,
)
TICKER_PAREN_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9]{1,9})\)")
TICKER_PAIR_RE = re.compile(
    r"\b([A-Z]{2,10})[-_/](?:USDT|USDC|USD|BTC|KRW|ETH|BNB|FDUSD)\b"
)
TICKER_QUOTE_RE = re.compile(
    r"\b([A-Z]{2,10})(?:USDT|USDC|BUSD|FDUSD)\b"
)
QUOTE_TOKENS = {
    "USDT", "USDC", "USD", "BUSD", "FDUSD", "TUSD", "KRW", "EUR", "TRY",
    "BTC", "ETH", "BNB", "THE", "AND", "FOR", "WILL", "WITH", "FROM",
    "SPOT", "MARGIN", "PERP", "PERPETUAL", "CONTRACTS", "TOKEN", "COIN",
    "NEW", "TAG", "SEED", "ZONE", "PAIR", "PAIRS", "MARKET", "MARKETS",
}

# Secrets currently loaded, used only to scrub log lines. Never written out.
_REDACT_SECRETS: list[str] = []


def resolve_data_dir(cli_value: str | None) -> Path:
    raw = (cli_value or os.environ.get("POLLER_DATA_DIR") or "data").strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def configure_paths(data_dir: Path) -> None:
    """Point every data file at `data_dir` and create it."""
    global DATA_DIR, QUEUE_PATH, CURSOR_PATH, HEARTBEAT_PATH
    global STATE_PATH, LOG_PATH, PID_PATH, LOCK_PATH
    DATA_DIR = data_dir
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH = DATA_DIR / "exchange_queue.jsonl"
    CURSOR_PATH = DATA_DIR / "exchange_queue.cursor"
    HEARTBEAT_PATH = DATA_DIR / "heartbeat.json"
    STATE_PATH = DATA_DIR / "state.json"
    LOG_PATH = DATA_DIR / "exchange_poller.log"
    PID_PATH = DATA_DIR / "exchange_poller.pid"
    LOCK_PATH = DATA_DIR / "exchange_poller.lock"


def webhook_env_path() -> Path | None:
    explicit = os.environ.get("WEBHOOK_ENV_FILE") or os.environ.get(
        "EXCHANGE_WEBHOOK_ENV_FILE"
    )
    if explicit:
        return Path(explicit).expanduser()
    if _LEGACY_WEBHOOK_ENV.exists():
        return _LEGACY_WEBHOOK_ENV
    return None


def redact(text: str) -> str:
    """Remove webhook URL and key if they ever appear in a string."""
    out = text
    for secret in _REDACT_SECRETS:
        if secret and secret in out:
            out = out.replace(secret, "[redacted]")
    return out


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not _REDACT_SECRETS:
            return True
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        if record.exc_info and record.exc_info[0] is not None:
            record.exc_text = redact(
                "".join(traceback.format_exception(*record.exc_info))
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def remember_secrets_for_redaction() -> None:
    """Load webhook config so later log lines can be scrubbed. Do not log it."""
    url, key, _sources = load_webhook_config()
    _REDACT_SECRETS.clear()
    for value in (url, key):
        if value and len(value) >= 8:
            _REDACT_SECRETS.append(value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc_iso(value: Any) -> str | None:
    """Best-effort conversion of many timestamp shapes to UTC ISO-8601."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).strip()
    if not text:
        return None
    # RSS / email dates
    try:
        parsed = email.utils.parsedate_to_datetime(text)
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        pass
    # ISO-8601, including offsets without colon and space-separated KST
    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            # Naive timestamps from Bithumb are KST.
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass
    # "2026-11-13 08:43:00" already handled by fromisoformat after space
    return None


def classify(title: str, catalog: str | None = None) -> str:
    text = title or ""
    cat = (catalog or "").lower()
    if DELIST_RE.search(text) or "delist" in cat:
        return "delisting"
    if LISTING_RE.search(text) or "listing" in cat:
        return "listing"
    if TAG_RE.search(text):
        return "tag"
    return "other"


def extract_tickers(title: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        t = token.upper()
        if t in QUOTE_TOKENS or t in seen or not (2 <= len(t) <= 10):
            return
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", t):
            return
        seen.add(t)
        found.append(t)

    for m in TICKER_PAREN_RE.finditer(title or ""):
        add(m.group(1))
    for m in TICKER_PAIR_RE.finditer(title or ""):
        add(m.group(1))
    for m in TICKER_QUOTE_RE.finditer(title or ""):
        add(m.group(1))
    return found


def make_item(
    exchange: str,
    item_id: str,
    title: str,
    url: str,
    first_published: Any,
    typ: str | None = None,
    tickers: list[str] | None = None,
    catalog: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    title = (title or "").strip()
    return {
        "exchange": exchange,
        "id": str(item_id),
        "title": title,
        "url": url or "",
        "first_published_utc": to_utc_iso(first_published),
        "first_seen_utc": utcnow_iso(),
        "type": typ or classify(title, catalog),
        "tickers": tickers if tickers is not None else extract_tickers(title),
        "catalog": catalog,
        "source": source,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class SoftTimeout(Exception):
    """Deadline exceeded in a worker thread (socket timeout may have been ignored)."""


def call_with_timeout(fn, timeout: float, description: str = "call"):
    """Run fn() in a daemon thread and raise SoftTimeout if it exceeds `timeout`."""
    q: queue.Queue = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            q.put((True, fn()))
        except Exception as exc:  # noqa: BLE001 — pass through to caller
            q.put((False, exc))

    t = threading.Thread(target=worker, name=f"to-{description[:40]}", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise SoftTimeout(f"{description} timed out after {timeout}s")
    try:
        ok, val = q.get_nowait()
    except queue.Empty as e:
        raise SoftTimeout(f"{description} timed out after {timeout}s") from e
    if ok:
        return val
    raise val


def _read_limited(fp, limit: int = MAX_BODY_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        buf = fp.read(65536)
        if not buf:
            break
        total += len(buf)
        if total > limit:
            raise OSError(f"response larger than {limit} bytes")
        chunks.append(buf)
    return b"".join(chunks)


class HttpError(Exception):
    def __init__(self, status: int, url: str, snippet: str = "", blocked: bool = False):
        self.status = status
        self.url = url
        self.snippet = snippet
        self.blocked = blocked
        kind = "blocked" if blocked else "http"
        super().__init__(f"{kind} {status} for {url}")


def _looks_blocked(status: int, body: bytes, content_type: str) -> bool:
    if status in (401, 402, 407):
        return False
    text = body[:2000].decode("utf-8", "replace").lower()
    ctype = (content_type or "").lower()
    signs = (
        "attention required",
        "just a moment",
        "cf-mitigated",
        "forbidden-wrap",
        "awswafcookiedomainlist",
        "why have i been blocked",
        "checking your browser",
        "access denied",
        "cloudflare",
    )
    if status in (403, 202, 429) and any(s in text for s in signs):
        return True
    if status == 403 and "text/html" in ctype:
        return True
    if status == 202 and "text/html" in ctype:
        return True
    return False


def _http_get_inner(
    url: str,
    timeout: int,
    headers: dict[str, str],
) -> tuple[int, str, bytes, str]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = _read_limited(resp)
            ctype = resp.headers.get("Content-Type", "") or ""
            status = getattr(resp, "status", 200)
            final = resp.geturl()
            if _looks_blocked(status, body, ctype):
                raise HttpError(status, url, body[:300].decode("utf-8", "replace"), True)
            return status, ctype, body, final
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = _read_limited(e) or b""
        except Exception:
            pass
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
        blocked = _looks_blocked(e.code, body, ctype)
        raise HttpError(
            e.code, url, body[:300].decode("utf-8", "replace"), blocked
        ) from None
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise HttpError(0, url, str(reason), False) from None
    except (TimeoutError, socket.timeout, OSError) as e:
        raise HttpError(0, url, f"{type(e).__name__}: {e}", False) from None


def http_get(
    url: str,
    timeout: int = HTTP_TIMEOUT,
    headers: dict[str, str] | None = None,
    accept: str | None = None,
    referer: str | None = None,
    origin: str | None = None,
) -> tuple[int, str, bytes, str]:
    h = {
        "User-Agent": USER_AGENT,
        "Accept": accept
        or "application/json, application/rss+xml, application/atom+xml, "
        "application/xml, text/xml, text/html;q=0.8, */*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        "Cache-Control": "no-cache",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if referer:
        h["Referer"] = referer
    if origin:
        h["Origin"] = origin
    if headers:
        h.update(headers)
    # Socket timeout plus a slightly longer thread deadline, so a stuck
    # DNS/TLS/read cannot freeze the poll loop (this was the heartbeat gap).
    hard = max(float(timeout) + 5.0, float(timeout) * 1.25)
    try:
        return call_with_timeout(
            lambda: _http_get_inner(url, timeout, h),
            timeout=hard,
            description=f"GET {url}",
        )
    except SoftTimeout as e:
        raise HttpError(0, url, str(e), False) from None


def http_json(url: str, **kwargs: Any) -> Any:
    status, ctype, body, _final = http_get(
        url, accept="application/json, */*;q=0.5", **kwargs
    )
    if "json" not in (ctype or "").lower() and not body.lstrip().startswith((b"{", b"[")):
        raise HttpError(status, url, f"non-json content-type={ctype}", False)
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise HttpError(status, url, f"invalid json: {e}", False) from None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
class SourceFetch:
    def __init__(
        self,
        name: str,
        items: list[dict[str, Any]] | None = None,
        endpoint: str | None = None,
        error: str | None = None,
        blocked: bool = False,
        fallback: str | None = None,
    ):
        self.name = name
        self.items = items or []
        self.endpoint = endpoint
        self.error = error
        self.blocked = blocked
        self.fallback = fallback

    @property
    def ok(self) -> bool:
        return self.error is None


def _try_endpoints(attempts: list[tuple[str, str, dict[str, Any]]]) -> tuple[str, str, Any]:
    """Try (label, url, kwargs) in order. Return (label, url, parsed json/body)."""
    last_err: Exception | None = None
    last_blocked = False
    last_url = ""
    for label, url, kwargs in attempts:
        last_url = url
        try:
            kw = dict(kwargs)
            kind = kw.pop("_kind", "json")
            if kind == "json":
                data = http_json(url, **kw)
            else:
                data = http_get(url, **kw)
            return label, url, data
        except HttpError as e:
            last_err = e
            last_blocked = last_blocked or e.blocked
            continue
    if last_err is None:
        raise HttpError(0, last_url, "no endpoints configured", False)
    if isinstance(last_err, HttpError):
        raise last_err
    raise HttpError(0, last_url, str(last_err), last_blocked)


def fetch_binance() -> SourceFetch:
    # binance.com composite is CloudFront-403 from this box; apex on
    # binance.com and composite on binance.info both work. One unscoped
    # list/query returns the main catalogs (listings, delistings, news, …).
    attempts = [
        (
            "binance.com apex CMS",
            "https://www.binance.com/bapi/apex/v1/public/apex/cms/article/list/query"
            "?type=1&pageNo=1&pageSize=20",
            {"referer": "https://www.binance.com/"},
        ),
        (
            "binance.info composite CMS",
            "https://www.binance.info/bapi/composite/v1/public/cms/article/list/query"
            "?type=1&pageNo=1&pageSize=20",
            {"referer": "https://www.binance.info/"},
        ),
        (
            "binance.info listings catalog 48",
            "https://www.binance.info/bapi/composite/v1/public/cms/article/list/query"
            "?type=1&catalogId=48&pageNo=1&pageSize=20",
            {"referer": "https://www.binance.info/"},
        ),
    ]
    try:
        label, url, data = _try_endpoints(attempts)
    except HttpError as e:
        # RSS on binance.com has been WAF-blocked (HTTP 202) from this box.
        rss_err = None
        for rss_url in (
            "https://www.binance.com/en/support/announcement/rss",
            "https://www.binance.info/en/support/announcement/rss",
        ):
            try:
                _status, _ctype, body, _final = http_get(
                    rss_url, accept="application/rss+xml, application/xml, text/xml"
                )
                items = _parse_rss_items(body, "binance")
                return SourceFetch(
                    "binance",
                    items=items,
                    endpoint=rss_url,
                    fallback="rss after CMS failed",
                )
            except HttpError as re:
                rss_err = re
        err = f"{e}; rss also failed: {rss_err}" if rss_err else str(e)
        return SourceFetch("binance", error=err, blocked=e.blocked, endpoint=e.url)

    catalogs = ((data or {}).get("data") or {}).get("catalogs") or []
    if (data or {}).get("code") not in (None, "000000", 0, "0"):
        return SourceFetch(
            "binance",
            error=f"cms code={(data or {}).get('code')} message={(data or {}).get('message')}",
            endpoint=url,
        )
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for cat in catalogs:
        cat_name = cat.get("catalogName") or ""
        for art in cat.get("articles") or []:
            aid = str(art.get("id") or art.get("code") or "")
            if not aid or aid in seen_ids:
                continue
            seen_ids.add(aid)
            code = art.get("code") or aid
            title = art.get("title") or ""
            items.append(
                make_item(
                    exchange="binance",
                    item_id=aid,
                    title=title,
                    url=f"https://www.binance.com/en/support/announcement/{code}",
                    first_published=art.get("releaseDate") or art.get("publishDate"),
                    catalog=cat_name,
                    source=label,
                )
            )
    fallback = None if "apex" in label else f"used {label} (binance.com composite blocked)"
    return SourceFetch("binance", items=items, endpoint=url, fallback=fallback)


def fetch_upbit() -> SourceFetch:
    # /api/v1/notices is gone (404). The public announcements API works
    # from this box with a browser UA. KR first; SG/ID share the schema
    # and are last-resort fallbacks if KR is blocked.
    kr_headers = {
        "referer": "https://upbit.com/service_center/notice",
        "origin": "https://upbit.com",
    }
    attempts = [
        (
            "kr announcements all",
            "https://api-manager.upbit.com/api/v1/announcements"
            "?os=web&page=1&per_page=20&category=all",
            dict(kr_headers),
        ),
        (
            "kr announcements trade",
            "https://api-manager.upbit.com/api/v1/announcements"
            "?os=web&page=1&per_page=20&category=trade",
            dict(kr_headers),
        ),
        (
            "sg announcements all",
            "https://sg-api-manager.upbit.com/api/v1/announcements"
            "?os=web&page=1&per_page=20&category=all",
            {
                "referer": "https://sg.upbit.com/service_center/notice",
                "origin": "https://sg.upbit.com",
            },
        ),
        (
            "id announcements all",
            "https://id-api-manager.upbit.com/api/v1/announcements"
            "?os=web&page=1&per_page=20&category=all",
            {
                "referer": "https://id.upbit.com/service_center/notice",
                "origin": "https://id.upbit.com",
            },
        ),
    ]
    try:
        label, url, data = _try_endpoints(attempts)
    except HttpError as e:
        return SourceFetch("upbit", error=str(e), blocked=e.blocked, endpoint=e.url)

    if label.startswith("sg"):
        notice_base = "https://sg.upbit.com/service_center/notice?id="
    elif label.startswith("id"):
        notice_base = "https://id.upbit.com/service_center/notice?id="
    else:
        notice_base = "https://upbit.com/service_center/notice?id="

    payload = (data or {}).get("data") or data or {}
    notices = payload.get("notices") or payload.get("list") or []
    fixed = payload.get("fixed_notices") or []
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in list(notices) + list(fixed):
        if not isinstance(row, dict):
            continue
        aid = str(row.get("id") or row.get("uuid") or "")
        if not aid or aid in seen_ids:
            continue
        seen_ids.add(aid)
        title = row.get("title") or ""
        items.append(
            make_item(
                exchange="upbit",
                item_id=aid,
                title=title,
                url=notice_base + aid,
                first_published=row.get("first_listed_at") or row.get("listed_at"),
                catalog=row.get("category") or row.get("thread_name"),
                source=label,
            )
        )
    fallback = None
    if not label.startswith("kr"):
        fallback = f"used {label} (KR api-manager failed)"
    return SourceFetch("upbit", items=items, endpoint=url, fallback=fallback)


def fetch_bithumb() -> SourceFetch:
    # feed-api is the canonical JSON source (api.bithumb.com 302s there).
    # A custom UA was Cloudflare-403; a browser UA + Referer/Origin works.
    bithumb_kw = {
        "referer": "https://feed.bithumb.com/notice",
        "origin": "https://feed.bithumb.com",
        "headers": {"Accept": "application/json, */*;q=0.5"},
    }
    attempts = [
        (
            "feed-api.bithumb.com/v1/notices",
            "https://feed-api.bithumb.com/v1/notices?count=20",
            dict(bithumb_kw),
        ),
        (
            "api.bithumb.com/v1/notices",
            "https://api.bithumb.com/v1/notices?count=20",
            dict(bithumb_kw),
        ),
    ]
    try:
        label, url, data = _try_endpoints(attempts)
    except HttpError as e:
        return SourceFetch("bithumb", error=str(e), blocked=e.blocked, endpoint=e.url)

    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url_item = row.get("pc_url") or row.get("url") or ""
        mid = re.search(r"/notice/(\d+)", url_item)
        aid = mid.group(1) if mid else (row.get("id") or url_item)
        aid = str(aid)
        if not aid or aid in seen_ids:
            continue
        seen_ids.add(aid)
        title = row.get("title") or ""
        cats = row.get("categories") or []
        catalog = cats[0] if cats else None
        if isinstance(cats, list) and cats:
            catalog = ", ".join(str(c) for c in cats)
        items.append(
            make_item(
                exchange="bithumb",
                item_id=aid,
                title=title,
                url=url_item or f"https://feed.bithumb.com/notice/{aid}",
                first_published=row.get("published_at") or row.get("modified_at"),
                catalog=catalog,
                source=label,
            )
        )
    return SourceFetch("bithumb", items=items, endpoint=url)


def _parse_rss_items(body: bytes, exchange: str, source: str = "rss") -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    items: list[dict[str, Any]] = []
    # RSS 2.0
    for it in root.findall("./channel/item") + root.findall("channel/item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or link or title).strip()
        pub = it.findtext("pubDate") or it.findtext("published")
        items.append(
            make_item(
                exchange=exchange,
                item_id=guid or link or title,
                title=title,
                url=link,
                first_published=pub,
                source=source,
            )
        )
    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for it in root.findall("{http://www.w3.org/2005/Atom}entry") + root.findall(
        "a:entry", ns
    ):
        title = (it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link_el = it.find("{http://www.w3.org/2005/Atom}link")
        link = ""
        if link_el is not None:
            link = (link_el.get("href") or link_el.text or "").strip()
        guid = (
            it.findtext("{http://www.w3.org/2005/Atom}id") or link or title
        ).strip()
        pub = it.findtext("{http://www.w3.org/2005/Atom}published") or it.findtext(
            "{http://www.w3.org/2005/Atom}updated"
        )
        items.append(
            make_item(
                exchange=exchange,
                item_id=guid or link or title,
                title=title,
                url=link,
                first_published=pub,
                source=source,
            )
        )
    return items


def _coinbase_blog_items(html: bytes) -> list[dict[str, Any]]:
    text = html.decode("utf-8", "replace")
    m = re.search(
        r'<script id="server-app-state" type="application/json">(.*?)</script>',
        text,
        re.S,
    )
    if not m:
        return []
    try:
        state = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    bridge = state.get("suspenseBridgeData")
    if isinstance(bridge, str):
        try:
            bridge = json.loads(bridge)
        except json.JSONDecodeError:
            return []
    articles: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "publicationDate" in obj and "title" in obj and "slug" in obj:
                articles.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(bridge)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for art in articles:
        slug = art.get("slug") or ""
        if not isinstance(slug, str) or "/blog/" not in slug:
            continue
        # homepage itself
        if slug.rstrip("/") in ("/blog", "/en/blog", "/en-nl/blog"):
            continue
        aid = str(art.get("id") or slug)
        key = f"blog:{aid}"
        if key in seen:
            continue
        seen.add(key)
        if slug.startswith("/"):
            url = "https://www.coinbase.com" + slug
        else:
            url = slug
        items.append(
            make_item(
                exchange="coinbase",
                item_id=key,
                title=art.get("title") or "",
                url=url,
                first_published=art.get("publicationDate") or art.get("updatedAt"),
                source="coinbase.com/blog html+json",
            )
        )
    return items


def fetch_coinbase() -> SourceFetch:
    """Blog HTML (current posts + publication dates) and status RSS.

    Official listing announcements moved to @CoinbaseAssets / @CoinbaseMarkets
    on X. This poller does not call the X API. Medium and the investor Q4
    blog RSS were fetched but are stale (2016 / 2023) and are not used.
    """
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    endpoints_ok: list[str] = []
    blocked = False
    fallback_notes: list[str] = []

    blog_urls = [
        "https://www.coinbase.com/en/blog",
        "https://www.coinbase.com/blog",
    ]
    blog_ok = False
    for url in blog_urls:
        try:
            _status, _ctype, body, final = http_get(
                url,
                accept="text/html,application/xhtml+xml",
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            parsed = _coinbase_blog_items(body)
            if parsed:
                items.extend(parsed)
                endpoints_ok.append(final or url)
                blog_ok = True
                break
            errors.append(f"{url}: html parsed but 0 posts")
        except HttpError as e:
            blocked = blocked or e.blocked
            errors.append(f"blog {e}")

    # Status incidents: trading-support / outage notices (not listings).
    for url in (
        "https://status.coinbase.com/history.rss",
        "https://status.coinbase.com/api/v2/incidents.json",
    ):
        try:
            if url.endswith(".rss"):
                _status, _ctype, body, _final = http_get(
                    url, accept="application/rss+xml, application/xml, text/xml"
                )
                rss_items = _parse_rss_items(body, "coinbase", source="status.coinbase.com rss")
                for it in rss_items:
                    it["id"] = "status:" + str(it["id"])
                items.extend(rss_items)
                endpoints_ok.append(url)
                break
            else:
                data = http_json(url)
                for row in (data or {}).get("incidents") or []:
                    iid = str(row.get("id") or "")
                    if not iid:
                        continue
                    short = row.get("shortlink") or f"https://status.coinbase.com/incidents/{iid}"
                    items.append(
                        make_item(
                            exchange="coinbase",
                            item_id="status:" + iid,
                            title=row.get("name") or "",
                            url=short,
                            first_published=row.get("created_at")
                            or row.get("started_at"),
                            source="status.coinbase.com api",
                        )
                    )
                endpoints_ok.append(url)
                break
        except HttpError as e:
            blocked = blocked or e.blocked
            errors.append(f"status {e}")

    if not items:
        return SourceFetch(
            "coinbase",
            error="; ".join(errors) or "no items",
            blocked=blocked,
            endpoint=blog_urls[0],
        )
    fallback = None
    if not blog_ok:
        fallback = "status feed only; blog html failed"
        fallback_notes.append(fallback)
    note = "; ".join(fallback_notes) if fallback_notes else None
    if errors and note:
        note = note + "; also: " + "; ".join(errors)
    return SourceFetch(
        "coinbase",
        items=items,
        endpoint="; ".join(endpoints_ok),
        fallback=note,
        error=None,
    )


SOURCES = {
    "binance": fetch_binance,
    "upbit": fetch_upbit,
    "bithumb": fetch_bithumb,
    "coinbase": fetch_coinbase,
}


# ---------------------------------------------------------------------------
# State, queue, heartbeat, logging
# ---------------------------------------------------------------------------
def setup_logging(to_stdout: bool = False) -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_ROTATE_BYTES:
        rotated = LOG_PATH.with_suffix(".log.1")
        try:
            if rotated.exists():
                rotated.unlink()
            LOG_PATH.rename(rotated)
        except OSError:
            pass
    logger = logging.getLogger("exchange_poller")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.filters.clear()
    fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(RedactFilter())
    logger.addHandler(fh)
    # Daemon mode stays quiet on stdout when a supervisor already redirects it.
    # --once / --probe always log to stdout so a CI job shows the cycle.
    if to_stdout or sys.stdout.isatty():
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.addFilter(RedactFilter())
        logger.addHandler(sh)
    logger.propagate = False
    return logger


log = logging.getLogger("exchange_poller")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {
            "seeded": False,
            "seen": {},
            "backoff": {},
            "webhook": {"last_post_utc": None, "pending": []},
        }
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("state unreadable (%s); starting fresh without dropping queue", e)
        return {
            "seeded": True,  # safer: do not re-enqueue unknown history
            "seen": {},
            "backoff": {},
            "webhook": {"last_post_utc": None, "pending": []},
            "state_reset_reason": str(e),
        }


def save_state(state: dict[str, Any]) -> bool:
    """Write state.json. Return True when the file contents actually change.

    A timestamp-only rewrite would make the data branch grow a commit every
    poll, so an equal document is left untouched.
    """
    seen = state.get("seen") or {}
    if len(seen) > SEEN_PRUNE_MAX:
        # keep most recently seen
        ranked = sorted(
            seen.items(),
            key=lambda kv: (kv[1] or {}).get("first_seen_utc") or "",
            reverse=True,
        )
        state["seen"] = dict(ranked[:SEEN_PRUNE_KEEP])
    if STATE_PATH.exists():
        try:
            current = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = None
        if current == state:
            return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        redact(json.dumps(state, ensure_ascii=False, indent=2) + "\n"),
        encoding="utf-8",
    )
    tmp.replace(STATE_PATH)
    return True


def append_queue(items: list[dict[str, Any]]) -> int:
    if not items:
        return 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            for it in items:
                # Stable required fields first; extras (catalog, source) kept.
                f.write(json.dumps(it, ensure_ascii=False, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return len(items)


def queue_line_count() -> int:
    if not QUEUE_PATH.exists() or QUEUE_PATH.stat().st_size == 0:
        return 0
    with QUEUE_PATH.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def init_cursor() -> None:
    if CURSOR_PATH.exists():
        return
    n = queue_line_count()
    CURSOR_PATH.write_text(str(n) + "\n", encoding="utf-8")
    log.info("initialized cursor at %s (line count %s)", CURSOR_PATH, n)


_last_heartbeat: dict[str, Any] = {}


def write_heartbeat(status: dict[str, Any] | None = None, *, phase: str | None = None) -> None:
    """Write heartbeat.json. If status is None, refresh the timestamp only.

    Fields: last run UTC, per-source ok/error/count, new item count, webhook status.
    """
    global _last_heartbeat
    if status:
        _last_heartbeat = dict(status)
    base = _last_heartbeat or {}
    payload: dict[str, Any] = {
        "last_run_utc": utcnow_iso(),
        "sources": base.get("sources") or {},
        "new_items": int(base.get("queued") or 0),
        "webhook": base.get("webhook") or "not_run",
    }
    if phase:
        payload["phase"] = phase
    for key in ("skipped_backoff", "seen", "blocked", "fallbacks", "seeded_now"):
        if key in base:
            payload[key] = base[key]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(
        redact(json.dumps(payload, ensure_ascii=False, indent=2) + "\n"),
        encoding="utf-8",
    )


def seen_key(item: dict[str, Any]) -> str:
    return f"{item.get('exchange')}:{item.get('id')}"


# ---------------------------------------------------------------------------
# Webhook (optional)
# ---------------------------------------------------------------------------
def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.error("could not read webhook env file: %s", e)
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'").strip('"')
        if k:
            out[k] = v
    return out


def load_webhook_config() -> tuple[str | None, str | None, list[str]]:
    """Return (url, key, source_names). Never log the values."""
    env_path = webhook_env_path()
    file_vals = _parse_env_file(env_path) if env_path is not None else {}
    url = (
        file_vals.get("WEBHOOK_URL")
        or file_vals.get("EXCHANGE_WEBHOOK_URL")
        or os.environ.get("EXCHANGE_WEBHOOK_URL")
        or os.environ.get("WEBHOOK_URL")
    )
    key = (
        file_vals.get("WEBHOOK_KEY")
        or file_vals.get("EXCHANGE_WEBHOOK_KEY")
        or os.environ.get("EXCHANGE_WEBHOOK_KEY")
        or os.environ.get("WEBHOOK_KEY")
    )
    sources: list[str] = []
    if env_path is not None and env_path.exists():
        sources.append("file")
    for name in (
        "EXCHANGE_WEBHOOK_URL",
        "EXCHANGE_WEBHOOK_KEY",
        "WEBHOOK_URL",
        "WEBHOOK_KEY",
    ):
        if os.environ.get(name):
            sources.append(f"env:{name}")
    url = url.strip() if url else None
    key = key.strip() if key else None
    return url, key, sources


def env_webhook_names_visible() -> list[str]:
    names = []
    for name in (
        "EXCHANGE_WEBHOOK_URL",
        "EXCHANGE_WEBHOOK_KEY",
        "WEBHOOK_URL",
        "WEBHOOK_KEY",
    ):
        if name in os.environ and os.environ.get(name):
            names.append(name)
    return names


def maybe_post_webhook(
    state: dict[str, Any],
    new_items: list[dict[str, Any]],
    *,
    immediate: bool = False,
) -> str:
    """POST pending announcements. Never log the webhook URL or key.

    Daemon mode keeps the 5-minute minimum interval and leaves items pending
    when rate-limited. ``--once`` passes immediate=True so the same run posts.
    Missing configuration does not raise: the status is ``not_configured`` and
    pending items stay in state for a later run (capped at 50).
    """
    url, key, _sources = load_webhook_config()
    hook = state.setdefault("webhook", {"last_post_utc": None, "pending": []})
    if new_items:
        hook.setdefault("pending", []).extend(
            {
                "exchange": it.get("exchange"),
                "id": it.get("id"),
                "title": it.get("title"),
                "url": it.get("url"),
                "type": it.get("type"),
                "tickers": it.get("tickers"),
                "first_published_utc": it.get("first_published_utc"),
                "first_seen_utc": it.get("first_seen_utc"),
            }
            for it in new_items
        )
        # cap pending
        hook["pending"] = hook["pending"][-50:]
    if not url or not key:
        return "not_configured"
    pending = hook.get("pending") or []
    if not pending:
        return "idle"
    last = hook.get("last_post_utc")
    if last and not immediate:
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if utcnow() - last_dt < timedelta(seconds=WEBHOOK_MIN_INTERVAL):
                return "rate_limited"
        except ValueError:
            pass
    body = json.dumps(
        {
            "source": "exchange_poller",
            "count": len(pending),
            "items": pending,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        WEBHOOK_AUTH_HEADER: WEBHOOK_AUTH_PREFIX + key,
        "User-Agent": USER_AGENT,
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
            resp.read()
        hook["last_post_utc"] = utcnow_iso()
        hook["pending"] = []
        log.info("webhook posted %s items status=%s", len(pending), status)
        return f"posted:{status}"
    except Exception as e:
        # Do not include request headers or URL (may contain the key in some setups).
        log.error("webhook POST failed: %s", type(e).__name__)
        return "error"


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------
def source_due(state: dict[str, Any], name: str) -> bool:
    info = (state.get("backoff") or {}).get(name) or {}
    nxt = info.get("next_try_utc")
    if not nxt:
        return True
    try:
        return utcnow() >= datetime.fromisoformat(nxt.replace("Z", "+00:00"))
    except ValueError:
        return True


def record_success(state: dict[str, Any], name: str) -> None:
    info = (state.get("backoff") or {}).get(name) or {}
    # Already healthy: leave last_ok_utc alone so a quiet poll does not
    # rewrite state.json (and grow the data-branch history) every run.
    if (
        info.get("fail_count") in (0, None)
        and not info.get("next_try_utc")
        and not info.get("last_error")
        and not info.get("blocked")
        and info.get("last_ok_utc")
    ):
        return
    state.setdefault("backoff", {})[name] = {
        "fail_count": 0,
        "next_try_utc": None,
        "last_error": None,
        "last_ok_utc": utcnow_iso(),
    }


def record_failure(state: dict[str, Any], name: str, error: str, blocked: bool) -> int:
    error = redact(error)
    info = state.setdefault("backoff", {}).setdefault(name, {})
    n = int(info.get("fail_count") or 0) + 1
    # 1, 2, 4, 8, … minutes, capped. Blocked sources back off a bit more.
    minutes = min(2 ** min(n - 1, 5), BACKOFF_CAP_SECONDS // 60)
    if blocked:
        minutes = max(minutes, 5)
    wait = min(minutes * 60, BACKOFF_CAP_SECONDS)
    # light jitter so failed sources don't sync up; keep the cap after jitter
    wait = int(wait * (0.85 + random.random() * 0.3))
    wait = min(wait, BACKOFF_CAP_SECONDS)
    info.update(
        {
            "fail_count": n,
            "next_try_utc": (utcnow() + timedelta(seconds=wait)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "last_error": error[:500],
            "blocked": blocked,
        }
    )
    return wait


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------
def _migrate_seeded_sources(state: dict[str, Any]) -> None:
    """Backfill seeded_sources only from items marked seeded at first start.

    A source that later starts working (or switches to a broader feed) must
    go through first-success seeding, so leftover first-page items are not
    enqueued as if they were new.
    """
    ss = state.setdefault("seeded_sources", {})
    counts: dict[str, int] = {}
    for key, meta in (state.get("seen") or {}).items():
        if not (meta or {}).get("seeded"):
            continue
        name = str(key).split(":", 1)[0]
        counts[name] = counts.get(name, 0) + 1
    for name, n in counts.items():
        if name not in ss:
            ss[name] = {
                "seeded_utc": state.get("seeded_utc") or utcnow_iso(),
                "count": n,
                "migrated": True,
            }


def _http_status_from_error(error: str | None) -> int | None:
    if not error:
        return None
    found = re.findall(r"\b(?:blocked|http) (\d+)\b", error)
    if not found:
        return None
    return int(found[-1])


def run_cycle(
    state: dict[str, Any],
    dry: bool = False,
    *,
    immediate_webhook: bool = False,
    deadline: float | None = None,
) -> dict[str, Any]:
    _migrate_seeded_sources(state)
    results: dict[str, SourceFetch] = {}
    skipped: list[str] = []
    for name, fn in SOURCES.items():
        if not dry and not source_due(state, name):
            skipped.append(name)
            log.info("skip %s (backoff until %s)", name, state["backoff"][name].get("next_try_utc"))
            continue
        source_timeout = float(SOURCE_TIMEOUT)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                log.error("%s: skipped, overall deadline exceeded", name)
                results[name] = SourceFetch(name, error="overall deadline exceeded")
                continue
            source_timeout = min(source_timeout, remaining)
        log.info("fetching %s", name)
        try:
            results[name] = call_with_timeout(
                fn, source_timeout, description=f"source {name}"
            )
        except SoftTimeout:
            log.error("%s: hard timeout after %ss", name, int(source_timeout))
            results[name] = SourceFetch(
                name, error=f"hard timeout after {int(source_timeout)}s"
            )
        except Exception as e:
            log.exception("unhandled error in %s", name)
            results[name] = SourceFetch(
                name, error=redact(f"unhandled {type(e).__name__}: {e}")
            )

    new_items: list[dict[str, Any]] = []
    seeded_now = False
    seen: dict[str, Any] = state.setdefault("seen", {})
    seeded_sources: dict[str, Any] = state.setdefault("seeded_sources", {})

    first_run = not state.get("seeded")
    for name, res in results.items():
        if res.ok:
            record_success(state, name)
            note = f"ok {len(res.items)} items via {res.endpoint}"
            if res.fallback:
                note += f" (fallback: {res.fallback})"
            log.info("%s: %s", name, note)
        else:
            wait = record_failure(state, name, res.error or "error", res.blocked)
            log.error(
                "%s: %s%s; backoff %ss",
                name,
                redact(res.error or ""),
                " [blocked]" if res.blocked else "",
                wait,
            )

        first_for_source = name not in seeded_sources
        seeded_this = 0
        for it in res.items:
            key = seen_key(it)
            if key in seen:
                continue
            if first_run or dry or (res.ok and first_for_source):
                seen[key] = {
                    "first_seen_utc": utcnow_iso(),
                    "title": it.get("title"),
                    "seeded": True,
                }
                seeded_this += 1
            else:
                seen[key] = {
                    "first_seen_utc": it.get("first_seen_utc") or utcnow_iso(),
                    "title": it.get("title"),
                }
                new_items.append(it)
        if res.ok and first_for_source and not dry:
            seeded_sources[name] = {
                "seeded_utc": utcnow_iso(),
                "count": len(res.items),
            }
            log.info(
                "%s: first success, seeded %s existing items, nothing enqueued",
                name,
                seeded_this,
            )
            seeded_now = True

    if first_run and not dry:
        state["seeded"] = True
        state["seeded_utc"] = utcnow_iso()
        seeded_now = True
        log.info(
            "first start: seeded %s existing items, nothing enqueued",
            sum(1 for v in seen.values() if v.get("seeded")),
        )

    queued = 0
    webhook_status = "skipped_dry" if dry else "not_run"
    if not dry:
        queued = append_queue(new_items)
        if queued:
            log.info("enqueued %s new items", queued)
        webhook_status = maybe_post_webhook(
            state, new_items, immediate=immediate_webhook
        )

    sources_summary: dict[str, Any] = {}
    for name, res in results.items():
        sources_summary[name] = {
            "ok": res.ok,
            "error": redact(res.error) if res.error else None,
            "count": len(res.items),
            "blocked": res.blocked,
            "http_status": _http_status_from_error(res.error),
            "endpoint": res.endpoint,
            "fallback": res.fallback,
        }
    for name in skipped:
        info = (state.get("backoff") or {}).get(name) or {}
        sources_summary[name] = {
            "ok": False,
            "error": info.get("last_error") or "skipped_backoff",
            "count": 0,
            "blocked": bool(info.get("blocked")),
            "http_status": _http_status_from_error(info.get("last_error")),
            "endpoint": None,
            "fallback": None,
            "skipped": True,
        }

    status = {
        "ok": [n for n, r in results.items() if r.ok],
        "error": [n for n, r in results.items() if not r.ok],
        "skipped_backoff": skipped,
        "queued": queued,
        "seeded_now": seeded_now,
        "seen": len(seen),
        "webhook": webhook_status,
        "sources": sources_summary,
        "endpoints": {
            n: (r.endpoint if r.ok else redact(r.error or "")) for n, r in results.items()
        },
        "fallbacks": {n: r.fallback for n, r in results.items() if r.fallback},
        "blocked": [n for n, r in results.items() if r.blocked],
    }
    return {"status": status, "results": results, "new_items": new_items}


def acquire_lock() -> Any:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def write_pid() -> None:
    PID_PATH.write_text(str(os.getpid()) + "\n", encoding="utf-8")


def loop(interval: int, jitter: int) -> None:
    state = load_state()
    init_cursor()
    log.info("poller starting pid=%s interval=%ss±%ss", os.getpid(), interval, jitter)
    url, key, sources = load_webhook_config()
    log.info(
        "webhook configured=%s sources=%s env_visible=%s",
        bool(url and key),
        ",".join(sources) or "none",
        ",".join(env_webhook_names_visible()) or "none",
    )
    write_heartbeat(
        {"ok": [], "error": [], "queued": 0, "webhook": "not_run", "sources": {}},
        phase="starting",
    )
    while True:
        # Heartbeat first, so a hung source cannot leave the file stale.
        write_heartbeat(phase="cycle_start")
        t0 = time.monotonic()
        try:
            out = run_cycle(state, dry=False)
            save_state(state)
            write_heartbeat(out["status"])
        except Exception:
            log.exception("cycle failed")
            write_heartbeat(
                {"ok": [], "error": ["cycle"], "queued": 0, "webhook": "error", "sources": {}}
            )
        elapsed = time.monotonic() - t0
        # Monotonic clock: a wall-clock jump must not turn this into an hour-long sleep.
        target = interval + random.uniform(-jitter, jitter)
        wait = min(max(5.0, target - elapsed), float(interval + jitter))
        time.sleep(wait)


def print_probe_text(results: dict[str, SourceFetch]) -> str:
    lines = ["=== source probe ==="]
    for name in SOURCES:
        res = results.get(name)
        if res is None:
            lines.append(f"\n[{name}] not fetched")
            continue
        flag = "OK" if res.ok else ("BLOCKED" if res.blocked else "ERROR")
        lines.append(f"\n[{name}] {flag}")
        lines.append(f"  endpoint: {res.endpoint}")
        if res.fallback:
            lines.append(f"  fallback: {res.fallback}")
        if res.error:
            lines.append(f"  error: {res.error}")
        lines.append(f"  items: {len(res.items)}")
        for it in res.items[:5]:
            lines.append(
                "   - {type:10} {tickers!s:20} {first_published_utc} | {title}".format(
                    type=it.get("type"),
                    tickers=",".join(it.get("tickers") or []) or "-",
                    first_published_utc=it.get("first_published_utc") or "no-date",
                    title=(it.get("title") or "")[:110],
                )
            )
            lines.append(f"     id={it.get('id')} url={it.get('url')}")
    return "\n".join(lines) + "\n"


def run_once() -> int:
    """One poll cycle, then exit. Missing webhook config is not a failure."""
    state = load_state()
    init_cursor()
    url, key, sources = load_webhook_config()
    log.info(
        "once mode budget=%ss webhook_configured=%s sources=%s env_visible=%s",
        ONCE_BUDGET_SECONDS,
        bool(url and key),
        ",".join(sources) or "none",
        ",".join(env_webhook_names_visible()) or "none",
    )
    write_heartbeat(
        {"queued": 0, "webhook": "not_run", "sources": {}},
        phase="cycle_start",
    )
    deadline = time.monotonic() + ONCE_BUDGET_SECONDS
    try:
        out = run_cycle(
            state,
            dry=False,
            immediate_webhook=True,
            deadline=deadline,
        )
        save_state(state)
        write_heartbeat(out["status"])
    except Exception:
        log.exception("cycle failed")
        write_heartbeat(
            {
                "ok": [],
                "error": ["cycle"],
                "queued": 0,
                "webhook": "error",
                "sources": {},
            }
        )
        return 1
    print(redact(json.dumps(out["status"], ensure_ascii=False, indent=2)))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Exchange announcement poller")
    p.add_argument("--probe", action="store_true", help="fetch+parse once, print samples, no queue writes")
    p.add_argument("--once", action="store_true", help="run one real cycle (seeds on first start), then exit")
    p.add_argument("--interval", type=int, default=POLL_SECONDS)
    p.add_argument("--jitter", type=int, default=JITTER_SECONDS)
    p.add_argument(
        "--data-dir",
        default=None,
        help="directory for state.json, exchange_queue.jsonl, and heartbeat.json "
        "(default: POLLER_DATA_DIR or ./data)",
    )
    args = p.parse_args(argv)
    configure_paths(resolve_data_dir(args.data_dir))
    setup_logging(to_stdout=bool(args.once or args.probe or os.environ.get("POLLER_LOG_STDOUT") == "1"))
    remember_secrets_for_redaction()

    lock = None
    if not args.probe:
        lock = acquire_lock()
        if lock is None:
            log.error("another poller is already running")
            return 1
        write_pid()
    try:
        if args.probe:
            state = load_state()
            out = run_cycle(state, dry=True, deadline=time.monotonic() + ONCE_BUDGET_SECONDS)
            print(redact(print_probe_text(out["results"])), end="")
            return 0 if any(r.ok for r in out["results"].values()) else 2
        if args.once:
            return run_once()
        loop(args.interval, args.jitter)
        return 0
    finally:
        if lock is not None:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
