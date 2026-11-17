#!/usr/bin/env bash
# Commit poller runtime files on the orphan poller-data branch and push.
# state.json / exchange_queue.jsonl are committed only when they changed.
# heartbeat.json alone is committed at most once every 30 minutes.
# A non-fast-forward push is retried by rebasing onto origin/poller-data.
set -euo pipefail

DATA_DIR="${1:-${POLLER_DATA_DIR:-}}"
BRANCH="${POLLER_DATA_BRANCH:-poller-data}"
REMOTE="${POLLER_DATA_REMOTE:-origin}"
HEARTBEAT_INTERVAL="${POLLER_HEARTBEAT_INTERVAL:-1800}"

if [[ -z "${DATA_DIR}" ]]; then
  echo "usage: commit_data.sh <data-dir>" >&2
  exit 1
fi

cd "${DATA_DIR}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "not a git checkout: ${DATA_DIR}" >&2
  exit 1
fi

# Never commit the code tree by mistake (this file is pushed to a public branch).
if [[ -f exchange_poller/poller.py || -f .github/workflows/exchange-poller.yml ]]; then
  echo "refusing to commit: ${DATA_DIR} looks like the code checkout" >&2
  exit 1
fi

export GIT_TERMINAL_PROMPT=0
export GIT_AUTHOR_NAME="github-actions[bot]"
export GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"
export GIT_COMMITTER_NAME="${GIT_AUTHOR_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_AUTHOR_EMAIL}"

# checkout@v4 leaves a detached HEAD. Attach the data branch without
# touching dirty poller files (they are the run we are about to commit).
git checkout -q -B "${BRANCH}"

git_commit() {
  git -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      -c user.name="github-actions[bot]" \
      commit -m "$1"
}

# Union seen-sets and queue lines when a rebase conflicts, so an announcement
# id is never dropped (that would re-post it on the next run).
resolve_conflicts() {
  python3 - "${DATA_DIR}" <<'PY'
import json, subprocess, sys
from pathlib import Path

root = Path(sys.argv[1])
allowed = {"state.json", "exchange_queue.jsonl", "heartbeat.json"}

def git_bytes(stage: str, path: str):
    proc = subprocess.run(
        ["git", "show", f":{stage}:{path}"],
        cwd=root,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout

unmerged = subprocess.run(
    ["git", "diff", "--name-only", "--diff-filter=U"],
    cwd=root,
    capture_output=True,
    text=True,
    check=True,
).stdout.split()

extra = [name for name in unmerged if name not in allowed]
if extra:
    sys.stderr.write("unexpected conflict: %s\n" % ", ".join(extra))
    sys.exit(1)

def queue_lines(blob: bytes | None) -> list[bytes]:
    if not blob:
        return []
    out = []
    for line in blob.splitlines():
        if line.strip():
            out.append(line)
    return out

def merge_queue(upstream: bytes | None, replayed: bytes | None) -> bytes:
    seen = set()
    lines = []
    for line in queue_lines(upstream) + queue_lines(replayed):
        try:
            obj = json.loads(line.decode("utf-8"))
            key = (obj.get("exchange"), str(obj.get("id")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            key = line
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    if not lines:
        return b""
    return b"\n".join(lines) + b"\n"

def merge_state(upstream: dict, replayed: dict) -> dict:
    out = json.loads(json.dumps(upstream))
    seen = dict(upstream.get("seen") or {})
    for key, meta in (replayed.get("seen") or {}).items():
        if key not in seen:
            seen[key] = meta
            continue
        old = seen[key] or {}
        new = meta or {}
        old_ts = old.get("first_seen_utc") or "9999"
        new_ts = new.get("first_seen_utc") or "9999"
        if new_ts < old_ts:
            seen[key] = new
    out["seen"] = seen

    seeded = dict(upstream.get("seeded_sources") or {})
    for key, meta in (replayed.get("seeded_sources") or {}).items():
        seeded.setdefault(key, meta)
    out["seeded_sources"] = seeded

    def stamp(info: dict | None) -> str:
        if not info:
            return ""
        return str(info.get("last_ok_utc") or info.get("next_try_utc") or "")

    backoff = dict(upstream.get("backoff") or {})
    for name, info in (replayed.get("backoff") or {}).items():
        if stamp(info) >= stamp(backoff.get(name)):
            backoff[name] = info
    out["backoff"] = backoff

    left = upstream.get("webhook") or {}
    right = replayed.get("webhook") or {}
    pending = []
    have = set()
    for item in list(left.get("pending") or []) + list(right.get("pending") or []):
        if not isinstance(item, dict):
            continue
        key = (item.get("exchange"), str(item.get("id")))
        if key in have:
            continue
        have.add(key)
        pending.append(item)
    last_left = left.get("last_post_utc") or ""
    last_right = right.get("last_post_utc") or ""
    last = last_left if last_left >= last_right else last_right
    out["webhook"] = {"last_post_utc": last or None, "pending": pending[-50:]}

    if upstream.get("seeded") or replayed.get("seeded"):
        out["seeded"] = True
    utc_left = upstream.get("seeded_utc") or ""
    utc_right = replayed.get("seeded_utc") or ""
    if utc_left or utc_right:
        out["seeded_utc"] = utc_left if utc_left and (not utc_right or utc_left <= utc_right) else utc_right
    return out

for name in unmerged:
    # stage 2 = branch we are rebasing onto (upstream); stage 3 = replayed commit
    upstream = git_bytes("2", name)
    replayed = git_bytes("3", name)
    dest = root / name
    if name == "exchange_queue.jsonl":
        dest.write_bytes(merge_queue(upstream, replayed))
    elif name == "state.json":
        left = json.loads(upstream.decode("utf-8")) if upstream else {}
        right = json.loads(replayed.decode("utf-8")) if replayed else {}
        text = json.dumps(merge_state(left, right), ensure_ascii=False, indent=2) + "\n"
        dest.write_text(text, encoding="utf-8")
    elif name == "heartbeat.json":
        def load_hb(blob):
            if not blob:
                return {}
            try:
                return json.loads(blob.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
        left = load_hb(upstream)
        right = load_hb(replayed)
        chosen = right if (right.get("last_run_utc") or "") >= (left.get("last_run_utc") or "") else left
        dest.write_text(json.dumps(chosen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", name], cwd=root, check=True)
PY
}

continue_rebase() {
  if GIT_EDITOR=true git rebase --continue; then
    return 0
  fi
  # A resolved tree that matches upstream leaves an empty commit.
  if git diff --cached --quiet && git diff --quiet; then
    git rebase --skip
    return 0
  fi
  echo "rebase --continue failed" >&2
  git status --porcelain >&2 || true
  return 1
}

files=()
[[ -f state.json ]] && files+=("state.json")
[[ -f exchange_queue.jsonl ]] && files+=("exchange_queue.jsonl")
[[ -f heartbeat.json ]] && files+=("heartbeat.json")

if [[ ${#files[@]} -eq 0 ]]; then
  echo "no poller data files to commit"
  exit 0
fi

git add -- "${files[@]}"

state_or_queue_changed=0
if ! git diff --cached --quiet -- state.json exchange_queue.jsonl; then
  state_or_queue_changed=1
fi

if [[ "${state_or_queue_changed}" -eq 1 ]]; then
  added=0
  if ! git diff --cached --quiet -- exchange_queue.jsonl; then
    added=$(git diff --cached -- exchange_queue.jsonl | grep -c '^+{' || true)
    added=${added:-0}
  fi
  if [[ "${added}" -gt 0 ]]; then
    git_commit "poller: record ${added} new announcement(s)"
  else
    git_commit "poller: update state"
  fi
else
  if ! git diff --cached --quiet -- heartbeat.json; then
    now=$(date +%s)
    last=$(git log -1 --format=%ct -- heartbeat.json 2>/dev/null || echo 0)
    last=${last:-0}
    age=$((now - last))
    if [[ "${age}" -ge "${HEARTBEAT_INTERVAL}" ]]; then
      git_commit "poller: heartbeat"
    else
      git restore --staged --worktree -- heartbeat.json state.json exchange_queue.jsonl >/dev/null 2>&1 || \
        git reset -q HEAD -- state.json exchange_queue.jsonl heartbeat.json || true
      echo "skip commit: heartbeat is ${age}s old (interval ${HEARTBEAT_INTERVAL}s) and state is unchanged"
      exit 0
    fi
  else
    echo "skip commit: nothing changed"
    exit 0
  fi
fi

delay=4
for attempt in 1 2 3 4; do
  if git push "${REMOTE}" "HEAD:${BRANCH}"; then
    echo "pushed ${BRANCH}"
    exit 0
  fi
  echo "push failed (attempt ${attempt}); fetching and rebasing onto ${REMOTE}/${BRANCH}" >&2
  if ! git fetch "${REMOTE}" "${BRANCH}"; then
    echo "fetch failed (attempt ${attempt})" >&2
    sleep "${delay}"
    delay=$((delay * 2))
    continue
  fi
  if ! git rebase "${REMOTE}/${BRANCH}"; then
    resolve_conflicts
    continue_rebase
  fi
  sleep "${delay}"
  delay=$((delay * 2))
done

echo "push failed after retries" >&2
exit 1
