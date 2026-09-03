# YuukaBot

Discord 伺服器內 `@優香` 或回覆她的訊息即可對話。好感度為**全伺服器共用**，大家一起養成。

## 啟動

```bash
cd YuukaBot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 填入 DISCORD_TOKEN、DEEPSEEK_*、可選 FLUX_*
python run.py
```

Discord Developer Portal 請開啟 **Message Content Intent**。

## 加分／扣分流程

```text
玩家訊息
  → DeepSeek 回 JSON（reply + affection_change + score_tags）
  → AffectionScorer 規則層合併
       ├ chat     實質聊天 +1（每日上限）
       ├ work     報帳/預算/文件等 +3（每日上限）
       ├ dislike  亂花錢/泡麵/不報帳等 -5（每日下限）
       ├ calendar 生日 3/14、節日（需當日+相關行動）大加分，每年一次
       └ llm      模型語境建議（再 clamp）
  → 寫入 guild_bonds + score_events
  → 必要時觸發 FLUX CG
```

規則數值與關鍵詞在 [`characters/yuuka.yaml`](characters/yuuka.yaml) 的 `scoring` 區塊。  
人設全文在 [`characters/yuuka-system-prompt.txt`](characters/yuuka-system-prompt.txt)。

| 類型 | 何時加／扣 | 預設 |
|------|------------|------|
| 聊天 | 有實質內容的互動 | +1／日上限 8 |
| 工作 | 會計、報帳、整理文件、計算等 | +3／日上限 12 |
| 厭惡 | 亂花錢、課金、泡麵、邋遢、堆積文件等 | -5／日最多扣到 -20 |
| 生日 | 3/14 且有祝福或相關行動 | +15／年一次 |
| 節日 | 元旦、情人節、除夕睡衣趴回憶等 | +5~+10／年一次 |

後端不盲信模型：每日 cap、節日 `event_key` 防重複、最終 clamp。

## 指令

- `/affection` 本伺服器共用好感
- `/gallery` 最近 CG
- 老師用半形 `(` 或全形 `（` 開頭下設定（鎖定／關閉人設等）
