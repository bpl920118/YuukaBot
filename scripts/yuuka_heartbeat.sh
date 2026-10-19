#!/usr/bin/env bash
# YuukaBot heartbeat — check process + Logged in; restart via tmux session yuuka if down.
set -uo pipefail

ROOT="/workspace/YuukaBot"
SESSION="yuuka"
STATE_DIR="$ROOT/storage/watch"
LOCKDIR="/tmp/yuuka_heartbeat.lockdir"
LOG="$ROOT/yuuka.log"
MAX_RESTARTS=3
mkdir -p "$STATE_DIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "SKIP locked"
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
today_local() { TZ=Asia/Taipei date +"%Y-%m-%d"; }

process_alive() {
  pgrep -af 'python.*run\.py' 2>/dev/null | grep -F "$ROOT" | grep -v grep >/dev/null
}

capture_blob() {
  local blob=""
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    blob="$(tmux capture-pane -t "$SESSION" -p -S -100 2>/dev/null || true)"
  fi
  if [[ -f "$LOG" ]]; then
    blob+=$'\n'"$(tail -n 100 "$LOG" 2>/dev/null || true)"
  fi
  printf '%s' "$blob"
}

logged_in_recent() {
  capture_blob | grep -q 'Logged in as '
}

bot_name_from_log() {
  capture_blob | grep -oE 'Logged in as [^[:cntrl:]]+' | tail -n1 | sed 's/Logged in as //' | head -c 80 || echo "unknown"
}

restart_bot() {
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
}

healthy() {
  process_alive && logged_in_recent
}

NOW="$(ts)"

if healthy; then
  DAY="$(today_local)"
  LAST_DAY_FILE="$STATE_DIR/last_daily_ok_day"
  LAST_DAY="$(cat "$LAST_DAY_FILE" 2>/dev/null || true)"
  echo "OK $NOW process+logged_in bot=$(bot_name_from_log)"
  echo "MANUAL: 請在 Discord 打 /ping 確認延遲"
  if [[ "$LAST_DAY" != "$DAY" ]]; then
    echo "LOG_DAILY_OK day=$DAY bot=$(bot_name_from_log) still alive"
    echo "$DAY" > "$LAST_DAY_FILE"
  fi
  exit 0
fi

if ! process_alive; then
  SYMPTOM="無 process"
else
  SYMPTOM="無 Logged in（process 在但未見 Logged in as）"
fi

echo "DOWN $NOW symptom=$SYMPTOM"
attempt=0
success=0
while (( attempt < MAX_RESTARTS )); do
  attempt=$((attempt + 1))
  echo "RESTART attempt=$attempt/$MAX_RESTARTS"
  restart_bot
  if healthy; then
    success=1
    break
  fi
  sleep 3
done

NAME="$(bot_name_from_log)"
if (( success == 1 )); then
  echo "LOG_RESTARTED time=$NOW symptom=$SYMPTOM attempts=$attempt bot=$NAME ok=1"
  exit 0
fi

echo "NOTIFY_RESTART_FAILED time=$NOW symptom=$SYMPTOM attempts=$attempt bot=$NAME"
echo "NEXT: 檢查 $LOG、tmux capture-pane -t yuuka、.venv；已達 $MAX_RESTARTS 次上限"
exit 12
