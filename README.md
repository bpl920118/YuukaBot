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

## 指令

- `/gallery` 本伺服器最近 CG

老師用半形 `(` 或全形 `（` 開頭下設定（僅 `TEACHER_USER_ID`）：

- `（模型）` 查看目前模型／深度
- `（模型 flash）` / `（模型 pro）` 切換模型
- `（深度 關）` / `（深度 high）` / `（深度 max）` 切換思考深度
- `（生圖狀態）` 測試 WebUI 是否連得上
- `（生圖網址 http://100.x.y.z:7860）` 設定生圖 API（Tailscale）
- `（關閉生圖）` 關閉本伺服器生圖覆寫
- 鎖定／關閉人設等其餘設定同前

## CG 兩階段

1. **先上線（對話）**：`SD_WEBUI_URL=` 留空。
2. **再開生圖**：本機開 WebUI（`--api`），填 `http://127.0.0.1:7860`，或雲端填 Tailscale／對外 URL（例如 `http://100.x.y.z:7860`）後重啟 bot。
