# YuukaBot

Discord 伺服器內 `@` 機器人或回覆她的訊息即可對話。

## 啟動（本機 / Linux）

```bash
cd YuukaBot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
# 填入 DISCORD_TOKEN、DEEPSEEK_API_KEY
# DEEPSEEK_MODEL 預設 deepseek-v4-flash；要更高品質可改 deepseek-v4-pro
# 雲端先留空 SD_WEBUI_URL；本機生圖再填 http://127.0.0.1:7860 或 Tailscale URL
python run.py
```

Discord Developer Portal 請開啟 **Message Content Intent**。

雲端（Grok Bot）部署步驟見 [`DEPLOY_GROK.md`](DEPLOY_GROK.md)。

## 對話流程

```text
玩家訊息
  → DeepSeek 回 JSON（reply / emotion / trigger_cg / cg_scene）
  → 寫入訊息記憶
  → 若觸發 CG 且 SD_WEBUI_URL 已設定 → WebUI txt2img → 回傳圖片
  → SD_WEBUI_URL 空白時略過生圖（只回文字）
```

人設全文在 [`characters/yuuka-system-prompt.txt`](characters/yuuka-system-prompt.txt)。  
角色與風格錨點在 [`characters/yuuka.yaml`](characters/yuuka.yaml)。

## 指令（斜線 `/`）

在頻道輸入 `/` 即可從選單選指令（含說明文字）。對話仍用 `@` 機器人或回覆她的訊息。

### 公開

| 指令 | 說明 |
|------|------|
| `/gallery` | 本伺服器最近 CG |
| `/ping` | 測試機器人是否在線 |

對話裡每位成員都會被當成「老師」稱呼；下列設定指令仍僅 `TEACHER_USER_ID`（管理者）可用。

| 指令 | 說明 |
|------|------|
| `/model` | 查看或切換模型（`flash` / `pro`） |
| `/depth` | 查看或切換深度（`關` / `high` / `max`） |
| `/image status` | 測試 WebUI 是否連得上 |
| `/image url` | 設定生圖 API（Tailscale 等） |
| `/image off` | 關閉本伺服器生圖覆寫 |
| `/image test` | 強制出一張測試 CG |
| `/clear memory` | 清除本伺服器 bot 對話記憶 |
| `/clear gallery` | 清除 CG 資料庫紀錄 |
| `/clear layers` | 清除老師叠加設定 |
| `/clear channel` | 刪本頻道訊息（可填 `limit` / `after_time` / `after_message_id`） |
| `/clear bot` | 只刪 bot 自己發過的訊息 |
| `/mode lock` | 之後只回應管理者本人 |
| `/mode unlock` | 解除鎖定 |
| `/mode work` | 工作模式（關閉人設） |
| `/mode persona` | 恢復優香人設 |
| `/note` | 叠加一則老師設定 |

清除頻道訊息時，bot 需要 Discord 權限 **Manage Messages（管理訊息）**。超過 14 天的訊息無法批次刪除。  
從某則訊息起刪：在 Discord 開啟「開發者模式」→ 右鍵訊息「複製訊息 ID」→ 填入 `/clear channel` 的 `after_message_id`。

## CG 兩階段

1. **先上線（對話）**：`SD_WEBUI_URL=` 留空。
2. **再開生圖**：本機開 WebUI（`--api`），填 `http://127.0.0.1:7860`，或雲端填 Tailscale／對外 URL（例如 `http://100.x.y.z:7860`）後重啟 bot。
