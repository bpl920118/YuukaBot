#!/usr/bin/env bash
set -euo pipefail
cd /workspace/YuukaBot
mkdir -p storage/watch logs
exec python3 -u scripts/yuuka_twitter_ba_hourly.py "$@" 2>&1 | tee -a logs/twitter_ba_hourly.log
