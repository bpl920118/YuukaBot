# Deploy on Grok Bot (xAI cloud computer)

Goal: keep YuukaBot online 24/7 on the Grok cloud VM. Chat first; CG later via Tailscale / reachable WebUI URL.

## Prerequisites (you provide secrets to Grok — never commit them)

- `DISCORD_TOKEN`
- `DEEPSEEK_API_KEY`
- Optional: `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `TEACHER_USER_ID`
- Discord app: **Message Content Intent** enabled

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

1. On the home PC, start A1111/Forge with API (`--api`), ideally reachable via Tailscale.
2. In cloud `.env` set e.g. `SD_WEBUI_URL=http://100.x.y.z:7860` (and checkpoint name if needed).
3. Restart the bot process (kill old `python run.py`, start again in tmux/nohup).

## Update code

```bash
cd /workspace/YuukaBot
git pull
source .venv/bin/activate
pip install -r requirements.txt
# restart bot process
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
