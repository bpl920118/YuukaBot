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
cp .env.example .env   # if new; else merge new keys only
# Fill DISCORD_TOKEN + API keys. Leave SD_WEBUI_URL / HOME_VRAM_AGENT_URL empty at first.
mkdir -p storage/images
tmux new -s yuuka 'source .venv/bin/activate && python run.py'
```

Confirm log: `Logged in as ...`

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
3. 編輯 .env（保留密鑰，對齊 .env.example 新增欄位；勿把密鑰貼回對話）：
   - LLM_TEMPERATURE=0.95 / HOME_LLM_TEMPERATURE=0.9 / MOMOTALK_TEMPERATURE=0.95
   - LLM_MAX_TOKENS=2048（雲端長回覆；勿把完整 .env 貼回對話）
   - LORE_SCAN_DEPTH=6 / LORE_MAX_CHARS=900 / MEMORY_SUMMARY_MAX_CHARS=400
   - GEMINI_API_KEY=（建議填：主路空回 ≥2 次會熱備切 Gemini，不改 /api switch）
   - HOME_VRAM_AGENT_URL=（有 Tailscale+agent 再填 http://100.x:5010；否則留空）
   - HOME_VRAM_AGENT_TOKEN=yuuka-local
   - HOME_VRAM_RELOAD_LLM=true
   - HOME_VRAM_ENSURE_LLM_ON_CHAT=true
   - SD_WEBUI_URL=（要 CG 再填 http://100.x:7860；否則留空）
4. 重啟 bot（空回退避／Gemini 熱備在 clients/llm.py，需重啟才生效）
5. 確認 Logged in；Discord /api status → /api test
6. 回報結果（不要回報完整 API key）
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
