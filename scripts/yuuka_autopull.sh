#!/usr/bin/env bash
# YuukaBot autopull — fetch; if new commits, ff-only pull, deps, .env keys, ffmpeg, restart.
set -uo pipefail

ROOT="/workspace/YuukaBot"
SESSION="yuuka"
LOCKDIR="/tmp/yuuka_autopull.lockdir"
HB_LOCKDIR="/tmp/yuuka_heartbeat.lockdir"
LOG="$ROOT/yuuka.log"
STATE_DIR="$ROOT/storage/watch"
mkdir -p "$STATE_DIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "SKIP locked"
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

cd "$ROOT" || { echo "NOTIFY_AUTOPULL_FAIL cannot cd $ROOT"; exit 20; }

# Dirty = tracked changes only (M/D/A/R/U…). Untracked watch scripts/logs do not block.
DIRTY="$(git status --porcelain | grep -vE '^\?\?' || true)"
if [[ -n "$DIRTY" ]]; then
  FINGERPRINT="$(printf '%s' "$DIRTY" | sha256sum | awk '{print $1}')"
  DAY="$(TZ=Asia/Taipei date +%Y-%m-%d)"
  MARK="$STATE_DIR/last_dirty_notify"
  LAST="$(cat "$MARK" 2>/dev/null || true)"
  if [[ "$LAST" == "$DAY $FINGERPRINT" ]]; then
    echo "QUIET dirty unchanged (already notified today)"
    exit 0
  fi
  echo "LOG_AUTOPULL_DIRTY time=$(ts)"
  echo "STATUS:"
  git status --short
  echo "STOPPED: dirty tracked files — waiting for manual instruction (no reset --hard)"
  echo "$DAY $FINGERPRINT" > "$MARK"
  exit 21
fi

git fetch origin 2>&1 || { echo "NOTIFY_AUTOPULL_FAIL fetch failed"; exit 22; }

UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo origin/master)"
OLD_SHA="$(git rev-parse HEAD)"
NEW_SHA="$(git rev-parse "$UPSTREAM" 2>/dev/null || true)"

if [[ -z "$NEW_SHA" ]]; then
  echo "NOTIFY_AUTOPULL_FAIL cannot resolve upstream $UPSTREAM"
  exit 22
fi

# Nothing to pull if upstream has no commits we lack (equal or local-ahead only).
BEHIND_COUNT="$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)"
if [[ "$BEHIND_COUNT" == "0" ]]; then
  if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
    echo "QUIET no new commits HEAD=$OLD_SHA upstream=$UPSTREAM"
  else
    echo "QUIET local ahead only HEAD=$OLD_SHA upstream=$NEW_SHA (nothing to pull)"
  fi
  exit 0
fi

# Diverged / cannot ff
if ! git merge-base --is-ancestor HEAD "$UPSTREAM"; then
  echo "NOTIFY_AUTOPULL_FAIL time=$(ts) non-ff HEAD=$OLD_SHA upstream=$NEW_SHA behind=$BEHIND_COUNT"
  git status -sb
  exit 23
fi

CHANGELOG="$(git log --oneline "${OLD_SHA}..${NEW_SHA}" | head -n 30)"

if ! git pull --ff-only; then
  echo "NOTIFY_AUTOPULL_FAIL time=$(ts) git pull --ff-only failed OLD=$OLD_SHA"
  git status -sb
  exit 24
fi

ACTUAL_NEW="$(git rev-parse HEAD)"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -r requirements.txt -q 2>&1 | tail -n 20
else
  echo "NOTIFY_AUTOPULL_FAIL no .venv"
  exit 25
fi

align_env_keys() {
  local example=".env.example" envf=".env"
  [[ -f "$example" ]] || return 0
  [[ -f "$envf" ]] || touch "$envf"
  local added=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    local key="${line%%=*}"
    key="$(echo "$key" | sed 's/[[:space:]]//g')"
    [[ -z "$key" ]] && continue
    if ! grep -qE "^[[:space:]]*${key}=" "$envf" 2>/dev/null; then
      echo "$line" >> "$envf"
      added=$((added + 1))
      echo "ENV_ADDED_KEY $key"
    fi
  done < "$example"
  echo "ENV_ALIGN added=$added (existing values preserved)"
}
align_env_keys

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "INSTALL ffmpeg"
  if command -v apt-get >/dev/null 2>&1; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg 2>&1 | tail -n 15 || {
      echo "NOTIFY_AUTOPULL_FAIL ffmpeg install failed"
      exit 26
    }
  else
    echo "NOTIFY_AUTOPULL_FAIL ffmpeg missing and no apt-get"
    exit 26
  fi
else
  echo "ffmpeg ok: $(command -v ffmpeg)"
fi

# Serialize restart with heartbeat via mkdir lock
if ! mkdir "$HB_LOCKDIR" 2>/dev/null; then
  echo "NOTIFY_AUTOPULL_FAIL time=$(ts) heartbeat busy during restart; will retry next cycle"
  exit 27
fi
# extend trap to clear both
trap 'rmdir "$HB_LOCKDIR" 2>/dev/null || true; rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

tmux kill-session -t "$SESSION" 2>/dev/null || true
pgrep -af 'python.*run\.py' 2>/dev/null | grep -F "$ROOT" | grep -v grep | awk '{print $1}' | while read -r p; do
  kill "$p" 2>/dev/null || true
done
sleep 1
pgrep -af 'python.*run\.py' 2>/dev/null | grep -F "$ROOT" | grep -v grep | awk '{print $1}' | while read -r p; do
  kill -9 "$p" 2>/dev/null || true
done
sleep 1
: > "$LOG"
tmux new-session -d -s "$SESSION" "cd '$ROOT' && unset DISCORD_TOKEN YUUKA_DISCORD_TOKEN && source .venv/bin/activate && env -u DISCORD_TOKEN -u YUUKA_DISCORD_TOKEN python -u run.py 2>&1 | tee -a '$LOG'"
sleep 8

login_ok=0
blob=""
if tmux has-session -t "$SESSION" 2>/dev/null; then
  blob="$(tmux capture-pane -t "$SESSION" -p -S -100 2>/dev/null || true)"
fi
blob+=$'\n'"$(tail -n 100 "$LOG" 2>/dev/null || true)"
if echo "$blob" | grep -q 'Logged in as '; then
  login_ok=1
fi
BOT="$(echo "$blob" | grep -oE 'Logged in as [^[:cntrl:]]+' | tail -n1 | sed 's/Logged in as //' || echo unknown)"

echo "LOG_AUTOPULL_UPDATED time=$(ts)"
echo "OLD_SHA=$OLD_SHA"
echo "NEW_SHA=$ACTUAL_NEW"
echo "UPSTREAM=$UPSTREAM"
echo "CHANGELOG:"
echo "$CHANGELOG"
echo "RESTART_OK=$login_ok bot=$BOT"
echo "MANUAL: 請在 Discord 打 /ping 確認延遲"

if (( login_ok == 1 )); then
  exit 30
fi
echo "NEXT: pull succeeded but Logged in not seen — check tmux/log"
exit 31
