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
本機 SillyTavern 管卡、Tailscale 連家用 LLM／SD：見 [`docs/local-tavern.md`](docs/local-tavern.md)。

現有雲端 API（DeepSeek／Gemini／OpenAI）與 Discord `/api` **完整保留**；家用模是可選、自行填 URL。

## 對話流程

```text
玩家訊息
  → DeepSeek 回 JSON（reply / emotion / 可選畫面關鍵字）
  → 寫入訊息記憶
  → 更新伺服器共用好感（對話／拜託加分；課金等扣分；對白不顯示分數）
  → 先回 Discord 文字
  → 若好感 ≥ 門檻且已設定 SD_WEBUI_URL
      → 依當下對話／記憶組關鍵字 → WebUI txt2img → 再貼圖，並扣除門檻分數
  → SD_WEBUI_URL 空白時略過生圖（只回文字）
```

自動生圖由 **伺服器共用好感門檻** 觸發；關鍵字依當下劇情／記憶產生。管理者可用 `/image force` 強制生圖（不耗門檻）。

人設全文在 [`characters/yuuka-system-prompt.txt`](characters/yuuka-system-prompt.txt)。  
角色、計分與風格錨點在 [`characters/yuuka.yaml`](characters/yuuka.yaml)。

## 指令（斜線 `/`）

在頻道輸入 `/` 即可從選單選指令（含說明文字）。對話仍用 `@` 機器人或回覆她的訊息。

### 公開

| 指令 | 說明 |
|------|------|
| `/gallery` | 本伺服器最近 CG |
| `/ping` | 測試機器人是否在線 |
| `/score show` | 查看共用好感與生圖門檻（僅自己可見） |

對話裡每位成員都會被當成「老師」稱呼；下列設定指令仍僅 `TEACHER_USER_ID`（管理者）可用。

| 指令 | 說明 |
|------|------|
| `/score threshold` | 設定達到多少分自動生圖（1～100） |
| `/score set` | 直接設定共用好感 |
| `/api switch` | 一鍵切換廠商＋模型（推薦） |
| `/api status` / `/api help` / `/api test` | 狀態／說明／連線測試 |
| `/api model` | 同廠商換模型（`flash`／`pro`／`lite` 或完整 id） |
| `/api depth` | 思考深度（`關`／`high`／`max`） |
| `/api immersion` | DeepSeek 角色沉浸開關 |
| `/api url` · `/api key` · `/api clear` | 進階覆寫／清回 `.env` |
| `/image status` · `url` · `off` · `test` · `force` | 生圖連線與強制出圖 |
| `/vram status` · `/vram switch` | 家用 GPU：文字 LLM ↔ 生圖 |
| `/clear memory` · `gallery` · `layers` | 清記憶／圖庫／老師設定 |
| `/clear messages` | 刪本頻道訊息（`scope`＝全部或只刪 bot） |
| `/mode lock` | 只回管理者／解除（`on`／`off`） |
| `/mode persona` | 優香人設／工作模式 |
| `/mode note` | 叠加一則老師設定 |

清除頻道訊息時，bot 需要 Discord 權限 **Manage Messages（管理訊息）**。超過 14 天的訊息無法批次刪除。  
從某則訊息起刪：在 Discord 開啟「開發者模式」→ 右鍵訊息「複製訊息 ID」→ 填入 `/clear messages` 的 `after_message_id`。

## CG 兩階段

1. **先上線（對話）**：`SD_WEBUI_URL=` 留空。
2. **再開生圖**：本機開 WebUI（`--api`），填 `http://127.0.0.1:7860`，或雲端填 Tailscale／對外 URL（例如 `http://100.x.y.z:7860`）後重啟 bot。
