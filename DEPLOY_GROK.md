# Deploy on Grok Bot (xAI cloud computer)

Goal: keep YuukaBot online 24/7 on the Grok cloud VM. Chat first; CG later via Tailscale / reachable WebUI URL.

## Prerequisites (you provide secrets to Grok — never commit them)

- `DISCORD_TOKEN`
- `DEEPSEEK_API_KEY`
- Optional: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `TEACHER_USER_ID`
- Discord app: **Message Content Intent** enabled

### Model choice (`DEEPSEEK_MODEL`)

| Model | Recommendation | Use |
|-------|----------------|-----|
| `deepseek-chat` | Avoid | Legacy name |
| `deepseek-reasoner` | Avoid | Legacy name |
| `deepseek-v4-flash` | Primary | Default / daily chat |
| `deepseek-v4-pro` | Secondary | Complex plot / heavier reasoning |

Default in `.env.example` is `deepseek-v4-flash`. To switch later: edit `.env` and restart the bot.

## Steps for Grok

```bash
cd /workspace
git clone https://github.com/bpl920118/YuukaBot.git
cd YuukaBot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set DISCORD_TOKEN and DEEPSEEK_API_KEY
# Leave SD_WEBUI_URL empty for chat-only
mkdir -p storage/images
```

Run detached (pick one):

```bash
# tmux
tmux new -s yuuka 'source .venv/bin/activate && python run.py'

# or nohup
source .venv/bin/activate
nohup python run.py > yuuka.log 2>&1 &
```

Verify logs show `Logged in as ...` and command sync.

## Later: enable CG

1. On the home PC:
   - Install/login **Tailscale**; note your machine IPv4 (`tailscale ip -4`).
   - Start A1111 / Forge with **API + listen**, e.g. `--api --listen` (port `7860`).
   - Load checkpoint matching `SD_WEBUI_CHECKPOINT` (default `kivotos-xl-2.0.safetensors`).
   - **8GB same GPU as Kobold:** also run `YuukaLocalLLM\start_vram_agent.bat` (port `5010`).
2. After Grok has pulled latest code and restarted the bot, in Discord as teacher:
   - `/image url` → `http://YOUR_TAILSCALE_IP:7860`
   - `/image status` → should show OK
3. Alternate: set in cloud `.env` and restart:
   - `SD_WEBUI_URL=http://YOUR_TAILSCALE_IP:7860`
   - Optional auto VRAM switch: `HOME_VRAM_AGENT_URL=http://YOUR_TAILSCALE_IP:5010` + matching `HOME_VRAM_AGENT_TOKEN`
4. To disable: `/image off` or clear env URL.

Grok cloud must reach the home WebUI (and optional VRAM agent) over Tailscale. Cursor itself never receives Discord image jobs.

## Optional: home LLM via Tailscale (Mode B)

Same Tailscale IP as WebUI. Example KoboldCPP (Qwen3-8B recommended):

1. Home: run KoboldCPP with OpenAI-compatible `/v1` (and VRAM agent if sharing GPU with SD).
2. Discord (teacher):  
   `/api url http://YOUR_TAILSCALE_IP:5001/v1`  
   `/api key local`  
   `/api model koboldcpp/Qwen3-8B-Q4_K_M`  
   `/api test`
3. Back to cloud: `/api clear`

SillyTavern stays on the **home PC only** (`127.0.0.1`) for card tuning — see [`docs/local-tavern.md`](docs/local-tavern.md). Sync card text into `characters/` then `git pull` on Grok.

Character stack on Grok after pull:

| File | Role |
|------|------|
| `characters/yuuka-system-prompt.txt` | Cloud full card |
| `characters/yuuka-system-prompt.local.txt` | Auto when `/api` points at home LLM |
| `characters/yuuka.yaml` | Lorebook / storyline / festivals |
| `characters/yuuka-world.yaml` | Locations / schedule / observances |

Ollama alternate port: `11434/v1`. LM Studio: `1234/v1`.

## Update code

```bash
cd /workspace/YuukaBot
git pull
source .venv/bin/activate
pip install -r requirements.txt
# restart bot process (keep existing .env secrets)
```

### API 切換（管理者 Discord）

`.env` 可同時放多組金鑰：`DEEPSEEK_API_KEY`、`GEMINI_API_KEY`、`OPENAI_API_KEY`。  
預設廠商用 `LLM_PROVIDER=deepseek|gemini|openai`。

```text
/api help            # 說明
/api switch          # 一次選「Gemini · 3.6 Flash」等（推薦）
/api status          # 看目前廠商／金鑰來源／model
/api test            # 最短連線測試
/api clear           # 清掉伺服器覆寫，改回 .env LLM_PROVIDER
/model flash|pro     # 只改「同廠商」模型別名
```

進階：`/api preset`、`/api url`、`/api key`、`/api model`。

### Pull prompt（更新時貼給 Grok）

```text
YuukaBot 有新 commit。請到 /workspace/YuukaBot：
1. git pull
2. source .venv/bin/activate && pip install -r requirements.txt
3. 編輯 .env（保留現有密鑰，對齊 .env.example 新增欄位；不要把密鑰貼回對話）：
   - LLM_PROVIDER / DEEPSEEK_* / 可選 GEMINI_*
   - LLM_TEMPERATURE=0.85
   - HOME_LLM_TEMPERATURE=0.7
   - MOMOTALK_TEMPERATURE=0.85
   - LORE_SCAN_DEPTH=6 / LORE_MAX_CHARS=900 / MEMORY_SUMMARY_MAX_CHARS=400
   - HOME_VRAM_AGENT_URL=（可先留空；家裡有 agent + Tailscale 再填 http://100.x:5010）
   - HOME_VRAM_AGENT_TOKEN=yuuka-local
   - HOME_VRAM_RELOAD_LLM=true
   - SD_WEBUI_URL=（可先留空；要 CG 再填 Tailscale :7860）
   不要用 gemini-2.5-flash（新帳號會 404）
4. 重啟 bot（tmux/nohup 的 python run.py）
5. 確認 log 有 Logged in
6. Discord：/api status → /api test（可選 /api switch）
7. 回報結果（不要回報完整 API key）
```

---

## Handoff prompt（直接貼給 Grok）

```text
請在這台雲端電腦部署／更新並常駐執行 Discord bot「YuukaBot」。

Repo: https://github.com/bpl920118/YuukaBot.git
工作目錄建議: /workspace/YuukaBot

步驟:
1. clone（若已存在則 git pull）
2. python3 -m venv .venv && source .venv/bin/activate（已有 venv 可略）
3. pip install -r requirements.txt
4. 若尚無 .env：從 .env.example 複製；若已有：保留密鑰，只補 .env.example 新增欄位
5. 我會另外提供／已提供 DISCORD_TOKEN 與 LLM API keys；寫入 .env，不要把密鑰貼回對話或 commit
6. 建議先：SD_WEBUI_URL= 與 HOME_VRAM_AGENT_URL= 留空（只跑雲端對話）
7. 用 tmux 或 nohup 常駐: python run.py
8. 確認 log 出現 Logged in，並回報 bot 使用者名稱與是否還缺設定

之後若要開 CG／家用 LLM／VRAM 自動切換，等我提供 Tailscale URL 再改 .env 並重啟。
```
