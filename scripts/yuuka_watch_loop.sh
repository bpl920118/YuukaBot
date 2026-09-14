#!/usr/bin/env bash
# Fallback supervisor if cron dies; flock keeps single instance.
LOCK=/tmp/yuuka_watch_loop.lock
exec 7>"$LOCK"
flock -n 7 || exit 0
while true; do
  /workspace/YuukaBot/scripts/yuuka_heartbeat.sh >> /workspace/YuukaBot/storage/watch/heartbeat.loop.log 2>&1 || true
  /workspace/YuukaBot/scripts/yuuka_autopull.sh >> /workspace/YuukaBot/storage/watch/autopull.loop.log 2>&1 || true
  sleep 900  # 15 min; heartbeat also via cron at 20
done
