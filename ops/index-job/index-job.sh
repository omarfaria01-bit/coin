#!/bin/bash
# Read-only GTASP10 index job. Never signs, never sends, never prints the API key.
# Usage: index-job.sh hourly|sample
set -euo pipefail

MODE="${1:-hourly}"
REPO="${COIN_REPO:-/opt/coin}"
WORK="${COIN_INDEX_WORKTREE:-/var/lib/coin/index-data}"
ENV_FILE="${COIN_INDEX_ENV:-/etc/coin/index.env}"
LOCK="${COIN_INDEX_LOCK:-/var/lib/coin/index-job.lock}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
if [[ -z "${HELIUS_API_KEY:-}" ]]; then
  echo "HELIUS_API_KEY is not set" >&2
  exit 2
fi

mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "index job already running" >&2
  exit 1
fi

cd "$REPO"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "repo is dirty; published index left unchanged" >&2
  exit 1
fi
git fetch origin main
git pull --ff-only origin main

run() {
  uv run python tools/run_index.py \
    --params "$REPO/index/params.json" \
    --overrides "$REPO/index/overrides.json" \
    --samples "$REPO/data/index/samples" \
    --out "$WORK/index/out" \
    --mints-file "${COIN_INDEX_MINTS:-$REPO/index/seed_mints.txt}" \
    --discover-pages "${COIN_INDEX_DISCOVER_PAGES:-100}" \
    "$@"
}

prepare_worktree() {
  mkdir -p "$(dirname "$WORK")"
  git fetch origin index-data || true
  if git show-ref --verify --quiet refs/remotes/origin/index-data; then
    if [[ ! -d "$WORK/.git" ]]; then
      git worktree add --detach "$WORK" origin/index-data
    fi
    git -C "$WORK" fetch origin index-data
    git -C "$WORK" reset --hard origin/index-data
  elif [[ ! -d "$WORK/.git" ]]; then
    git init -b index-data "$WORK"
    git -C "$WORK" remote add origin "$(git remote get-url origin)"
    git -C "$WORK" commit --allow-empty -m "index-data"
  fi
}

publish() {
  git -C "$WORK" add index/out
  if git -C "$WORK" diff --cached --quiet; then
    echo "no index change to publish"
    return 0
  fi
  git -C "$WORK" commit -m "index $(date -u +%Y-%m-%dT%H:%MZ)"
  if ! git -C "$WORK" push origin HEAD:index-data; then
    echo "push failed; remote index-data left unchanged" >&2
    git -C "$WORK" reset --hard origin/index-data 2>/dev/null || true
    exit 1
  fi
}

if [[ "$MODE" == "sample" ]]; then
  run --mode sample --as-of "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  exit 0
fi
if [[ "$MODE" != "hourly" ]]; then
  echo "mode must be hourly or sample" >&2
  exit 2
fi

prepare_worktree
AS_OF="$(date -u +%Y-%m-%dT%H:00:00Z)"
SAMPLE_AS_OF="$(date -u -d "$AS_OF - 1 second" +%Y-%m-%dT%H:%M:%SZ)"
run --mode sample --as-of "$SAMPLE_AS_OF" || echo "sample failed; older samples kept" >&2
run --mode rebalance --as-of "$AS_OF"
run --mode emergency --as-of "$AS_OF"
publish
