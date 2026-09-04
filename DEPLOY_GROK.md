# Deploy on Grok Bot (xAI cloud computer)

Goal: keep YuukaBot online 24/7 on the Grok cloud VM. Chat first; CG later via Tailscale / reachable WebUI URL.

## Prerequisites (you provide secrets to Grok — never commit them)

- `DISCORD_TOKEN`
- `DEEPSEEK_API_KEY`
- Optional: `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `TEACHER_USER_ID`
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
2. After Grok has pulled latest code and restarted the bot, in Discord as teacher:
   - `/image url` → `http://YOUR_TAILSCALE_IP:7860`
   - `/image status` → should show OK
3. Alternate: set `SD_WEBUI_URL` in cloud `.env` and restart (no Discord command needed).
4. To disable: `/image off` or clear env URL.

Grok cloud must reach the home WebUI over Tailscale (or another reachable URL). Cursor itself never receives Discord image jobs.

## Update code

```bash
cd /workspace/YuukaBot
git pull
source .venv/bin/activate
pip install -r requirements.txt
# restart bot process (keep existing .env secrets)
```

### API 切換（管理者 Discord）

```text
/api status          # 看目前 base／金鑰遮罩／model
/api preset gemini   # 或 deepseek / openai（改 base＋預設模型）
/api key <金鑰>      # 只自己看得到；勿公開貼
/api model gemini-2.5-flash
/api test            # 最短連線測試
/api clear           # 清掉伺服器覆寫，改回 .env
```

自訂廠商：`/api url https://...` + `/api key` + `/api model`（須 OpenAI 相容 `/chat/completions`）。

### Pull prompt（更新時貼給 Grok）

```text
YuukaBot 有新 commit。請到 /workspace/YuukaBot：
1. git pull
2. source .venv/bin/activate && pip install -r requirements.txt
3. 重啟 tmux/nohup 裡的 python run.py（保留現有 .env，不要覆寫密鑰）
4. 確認 log 有 Logged in，回報結果
5. 可用 /api status 查看目前 API；切 Gemini：/api preset gemini → /api key → /api test
```

---

## Handoff prompt（直接貼給 Grok）

```text
請在這台雲端電腦部署並常駐執行 Discord bot「YuukaBot」。

Repo: https://github.com/bpl920118/YuukaBot.git
工作目錄建議: /workspace/YuukaBot

步驟:
1. clone（若已存在則 git pull）
2. python3 -m venv .venv && source .venv/bin/activate
3. pip install -r requirements.txt
4. 從 .env.example 複製成 .env
5. 我會另外提供 DISCORD_TOKEN 與 DEEPSEEK_API_KEY；請寫入 .env，不要把密鑰貼回對話或 commit
6. SD_WEBUI_URL 先留空（只跑對話，先不要生圖）
7. 用 tmux 或 nohup 常駐: python run.py
8. 確認 log 出現 Logged in，並回報 bot 使用者名稱與是否還缺設定

之後若要開 CG，等我提供可連到的 SD WebUI URL（Tailscale），再改 .env 並重啟。
```
