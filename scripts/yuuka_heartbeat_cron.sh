#!/usr/bin/env bash
set -uo pipefail
STATE_DIR=/workspace/YuukaBot/storage/watch
mkdir -p "$STATE_DIR"
OUT=$(/workspace/YuukaBot/scripts/yuuka_heartbeat.sh 2>&1)
EC=$?
echo "$OUT" >> "$STATE_DIR/heartbeat.cron.log"
if echo "$OUT" | grep -qE 'NOTIFY_'; then
  {
    echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) heartbeat ec=$EC ===="
    echo "$OUT"
    echo
  } >> "$STATE_DIR/pending_notify.txt"
fi
exit 0
