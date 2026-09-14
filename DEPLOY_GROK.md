# Deploy on Grok Bot (xAI cloud computer)

Goal: keep YuukaBot online 24/7 on the Grok cloud VM. Chat first; CG / home LLM later via Tailscale.

## Prerequisites (secrets — never commit)

- `DISCORD_TOKEN`
- `DEEPSEEK_API_KEY`
- Optional: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `TEACHER_USER_ID`
- Discord: **Message Content Intent** on

### Model choice (`DEEPSEEK_MODEL`)

| Model | Use |
|-------|-----|
| `deepseek-v4-flash` | Primary daily chat |
| `deepseek-v4-pro` | Heavier reasoning |

## Steps for Grok

```bash
cd /workspace
git clone https://github.com/bpl920118/YuukaBot.git   # or: cd YuukaBot && git pull
cd YuukaBot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Voice music (/play): FFmpeg must be on PATH
sudo apt-get update && sudo apt-get install -y ffmpeg
ffmpeg -version   # confirm
cp .env.example .env   # if new; else merge new keys only
# Fill DISCORD_TOKEN + API keys. Leave SD_WEBUI_URL / HOME_VRAM_AGENT_URL empty at first.
mkdir -p storage/images
tmux new -s yuuka 'source .venv/bin/activate && python run.py'
```

Confirm log: `Logged in as ...`

### Voice music（`/play`）

- Bot 邀請權限需含 **Connect** + **Speak**（連線／說話）。
- 依賴：`yt-dlp`、`PyNaCl`（在 `requirements.txt`）+ 系統 **FFmpeg**。
- 支援 YouTube／YouTube Music 連結、歌名搜尋、播放清單（單次最多 50 首）。

---

## 連線打通（家裡 PC ↔ Grok）

在家裡取得 Tailscale IPv4：`tailscale ip -4`（下稱 `100.x`）。

| 服務 | 本機埠 | Grok `.env` / Discord | 家裡要開 |
|------|--------|------------------------|----------|
| 雲端文字 LLM | — | `LLM_PROVIDER` + API keys | 不用 |
| 家用文字 LLM（Kobold） | `5001` | `/api url http://100.x:5001/v1` | Kobold + 模型 |
| 生圖 WebUI | `7860` | `SD_WEBUI_URL=http://100.x:7860` 或 `/image url` | `webui-user.bat`（`--api --listen`） |
| VRAM 自動切換 | `5010` | `HOME_VRAM_AGENT_URL=http://100.x:5010` | `YuukaLocalLLM\start_vram_agent.bat` |

### 文字 LLM ↔ 生圖：自動切換

8GB 同卡時：

1. 家裡常駐 **`start_vram_agent.bat`**
2. Grok `.env` 填 `HOME_VRAM_AGENT_URL` + `HOME_VRAM_AGENT_TOKEN=yuuka-local`
3. `HOME_VRAM_RELOAD_LLM=true`、`HOME_VRAM_ENSURE_LLM_ON_CHAT=true`

行為：

| 時機 | 動作 |
|------|------|
| 要生 CG（達門檻／`/image test`） | 自動 `to_sd`（關 Kobold → 開 WebUI） |
| 生圖結束 | 自動 `to_llm`（可關 WebUI → 開 Kobold） |
| Discord 走家用 `/api` 聊天但 Kobold 掛了 | 自動切回文字 LLM |
| 手動 | `/vram status`、`/vram switch` |

日常建議：**聊天用雲端**；CG 才動家裡 GPU。Mode B（家用聊天）再開 Kobold + agent。

### Discord 驗收順序

```text
/api status → /api test
/image url http://100.x:7860 → /image status → /image test
/vram status →（可選）/vram switch
家用模：/api url http://100.x:5001/v1 → /api key local → /api model koboldcpp/Qwen3-8B-Q4_K_M → /api test
切回雲端：/api clear
```

Windows 防火牆需放行 **5001 / 7860 / 5010**（至少 Tailscale 介面）。

---

## Character files（pull 後即用）

| File | Role |
|------|------|
| `yuuka-system-prompt.txt` | 雲端長卡 |
| `yuuka-system-prompt.local.txt` | 家用短卡（自動） |
| `yuuka.yaml` | lorebook／storyline／節日 |
| `yuuka-world.yaml` | 地點／時段／節日世界表 |

---

## Pull prompt（貼給 Grok）

```text
YuukaBot 有新 commit。請到 /workspace/YuukaBot：
1. git pull
2. source .venv/bin/activate && pip install -r requirements.txt
3. 確認 FFmpeg（語音 /play）：command -v ffmpeg || sudo apt-get install -y ffmpeg
4. 編輯 .env（保留密鑰，對齊 .env.example 新增欄位；勿把密鑰貼回對話）：
   - LLM_TEMPERATURE=0.95 / HOME_LLM_TEMPERATURE=0.9 / MOMOTALK_TEMPERATURE=0.95
   - LLM_MAX_TOKENS=2048（雲端長回覆；勿把完整 .env 貼回對話）
   - LORE_SCAN_DEPTH=6 / LORE_MAX_CHARS=900 / MEMORY_SUMMARY_MAX_CHARS=400
   - GEMINI_API_KEY=（建議填：主路空回 ≥2 次會熱備切 Gemini，不改 /api switch）
   - HOME_VRAM_AGENT_URL=（有 Tailscale+agent 再填 http://100.x:5010；否則留空）
   - HOME_VRAM_AGENT_TOKEN=yuuka-local
   - HOME_VRAM_RELOAD_LLM=true
   - HOME_VRAM_ENSURE_LLM_ON_CHAT=true
   - SD_WEBUI_URL=（要 CG 再填 http://100.x:7860；否則留空）
5. 重啟 bot（空回退避／Gemini 熱備在 clients/llm.py，需重啟才生效）
6. 確認 Logged in；Discord /api status → /api test；語音可試 /play
7. 回報結果（不要回報完整 API key）
```

## Handoff prompt（全新／重裝）

```text
請部署／更新並常駐 Discord bot「YuukaBot」。
Repo: https://github.com/bpl920118/YuukaBot.git
目錄: /workspace/YuukaBot
1. clone 或 git pull
2. venv + pip install -r requirements.txt
3. .env 從 example 合併；我提供 DISCORD_TOKEN 與 LLM keys（勿貼回對話／勿 commit）
4. 先留空 SD_WEBUI_URL 與 HOME_VRAM_AGENT_URL（只跑雲端對話）
5. tmux/nohup: python run.py
6. 確認 Logged in 並回報 bot 名稱
之後我提供 Tailscale 100.x 再開 CG／家用 LLM／VRAM 自動切換。
```

## Heartbeat prompt（貼給 Grok｜常駐心跳）

```text
請在這台機器為 YuukaBot 掛一個常駐心跳監視（每 20 分鐘一次，可 15–30 分）。目錄固定 /workspace/YuukaBot；tmux session 名 yuuka。

你要做的事：
1. 寫一個可重複執行的檢查腳本（例如 scripts/yuuka_heartbeat.sh），邏輯如下：
   a. process：是否有 python … run.py（或 yuuka session 內還在跑）
   b. log：tmux capture-pane / 最近 log 是否出現過 Logged in as …
   c. 健康：process 在且近期有 Logged in → 視為 OK；否則視為掛了
   d. Discord /ping：你無法代使用者在手機點 slash；不要假裝測過。只在回報裡寫「請在 Discord 打 /ping 確認延遲」當人工驗收項。
2. 若掛了：保留 .env，重啟方式固定為
   - tmux kill-session -t yuuka 2>/dev/null || true
   - cd /workspace/YuukaBot && tmux new -d -s yuuka 'source .venv/bin/activate && python run.py'
   - 等數秒再 capture-pane，確認出現 Logged in as …
3. 用 cron 或 while+sleep 常駐跑上述腳本（每 20 分鐘）；機器重開後也要能自動回來（寫進 crontab 或開機腳本，並告訴我怎麼設的）。
4. 通知規則：
   - OK：安靜，不要每輪洗頻；最多每天摘要一次「仍活著」
   - 掛了並已重啟：立刻用這次對話回報——時間、症狀（無 process／無 Logged in）、重啟是否成功、bot 名稱
   - 重啟失敗：立刻回報錯誤與下一步建議；不要默默重試超過 3 次
5. 禁止：改 .env 密鑰、git push、把 token/key 貼回對話、亂殺其他 tmux session。
6. 做完後回報：腳本路徑、排程方式、第一次手動跑的結果。
```

## Auto-pull prompt（貼給 Grok｜盯新 commit）

```text
請在這台機器為 bpl920118/YuukaBot 掛「有新 commit 就自動更新並重啟」。目錄 /workspace/YuukaBot；遠端 origin；預設分支 master（若本地追蹤別的分支，以當前追蹤分支為準）。

你要做的事：
1. 寫腳本（例如 scripts/yuuka_autopull.sh）：
   a. cd /workspace/YuukaBot && git fetch origin
   b. 比較 HEAD 與 @{u}（或 origin/master）；沒有新 commit → 安靜結束
   c. 有新 commit → git pull --ff-only（失敗就停、回報，不要 force）
   d. source .venv/bin/activate && pip install -r requirements.txt
   e. 對齊 .env.example 只補「缺少的新鍵」、保留既有密鑰與既有值；不要覆寫我已填的值；不要把完整 .env 貼回對話
   f. 確認 ffmpeg 在 PATH（語音 /play）；沒有就 apt 安裝
   g. 重啟：tmux kill-session -t yuuka 2>/dev/null || true；再 tmux new -d -s yuuka 'source .venv/bin/activate && python run.py'
   h. 確認 Logged in as …；回報：舊 SHA → 新 SHA、簡短 changelog（git log --oneline 舊..新）、重啟是否成功
2. 排程：每 10–15 分鐘跑一次（cron 或 loop）；與心跳腳本可並存，不要互搶殺對方不相關的 process。
3. 衝突／dirty working tree：不要 git reset --hard；停下來回報 status，等我指示。
4. 禁止：git push、改 remote、洩漏密鑰、在沒有新 commit 時重啟 bot。
5. 做完後回報：腳本路徑、排程、第一次手動跑（可先 dry：只 fetch+比對）的結果。
```