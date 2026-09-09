# MomoTalk 主動劇情 v2（草案）

**狀態：草案／未實作**  
**與現行 runtime 無關** — 勿被 `core/world.py`、`core/pipeline.py`、bot 排程引用。  
現行仍使用：`yuuka-world.yaml` + `pick_moment` / `sticky_moment` + 老師 `@`／回覆才聊；probe 見 `scripts/probe_world_momotalk.py`。

本文只保存產品與資料設計共識，方便之後另開工程實作。工程量接近「新故事執行層」，不是在現有 sticky 場景上小改。

---

## 1. 目標

- 以原作 **MomoTalk 聊天軟件** 感：可主動傳訊、對話保留、老師有行動權、角色可提出約會／碰面。
- **人設卡不動**（`characters/*-system-prompt*.txt`）：不往卡裡加劇情設定。
- 故事發想來自可組合的 **事態素材**，與人設層分離。
- 一伺服器內 **所有使用者 = 一個老師**；任何人發言都推進同一條對話。
- 主動訊息可 **由管理員指定頻道**；未指定則不推播。

---

## 2. 與現行架構的關係

| 層 | 現行 | v2 草案 |
|----|------|---------|
| 人設卡 | 檔案唯讀 | 不變 |
| 世界表 | `locations` × `actions[loc]` + 節日 `action_extra` 併入行動池 | **事態卡（beat）** 為原子；節日不裸拼行動 |
| 場景注入 | 每輪 `sticky_moment` | 主動局期間用 session brief |
| 主動推播 | 僅 probe／未接 Discord | 綁定頻道 + 日更一次 |
| 記憶 | guild 共有 `Message` | 主動訊也寫入同一條記憶 |
| 好感 | guild 共有 `GuildBond` | 不變 |

---

## 3. 產品模型

### 3.1 共有老師

- 記憶／好感／MomoTalk session 皆為 **`guild_id + character_id`**。
- Prompt 標籤維持 `[老師xxxx]`（尾碼僅區分發言者），RP 上仍是單一「老師」。
- 多人衝突（A 答應、B 拒絕）：**後寫入覆蓋** session 狀態。

### 3.2 兩種模式

| 模式 | 含義 |
|------|------|
| `momotalk` | 短訊串；可 chat／hook／invite |
| `meetup` | 老師接受邀約後的見面／約會場景；注入同一局 brief |

原則：她可提議；是否赴約由老師訊息決定。不回就不推進；不可擅自當成已答應。

### 3.3 綁定頻道

建議指令（僅管理者／`TEACHER_USER_ID`）：

- `/momotalk here` — 目前頻道設為主動頻道
- `/momotalk off` — 清除綁定，停止主動推播
- `/momotalk status` — 頻道、mode、invite、上次／下次推播

`GuildSetting`（或旁表）新增例如 `momotalk_channel_id`（null = 不推播）。

MVP 建議：session 狀態 **只在綁定頻道更新**；其他頻道 `@` 仍走現行 pipeline，可讀共有記憶但不搶邀約狀態。

---

## 4. Session 狀態（每 guild × 角色）

```text
momotalk_channel_id   # null = 不主動推播
mode                  # idle | momotalk | meetup
invite_status         # none | pending | accepted | declined
cards[] / beat_id     # 本局事態
brief                 # 短場景摘要
opened_at / expires_at
last_proactive_at
next_fire_at          # 今日預定發送時刻
fire_date             # 該 next_fire 所屬本地日期
sent_date             # 今日已發送則記錄，防重複
```

主動訊息：`role=assistant`，寫入現有 `messages` 表。

---

## 5. 故事素材：事態卡（beat）

### 5.1 為什麼不用裸交叉

自由 `地點 × 事件 × 節日行動` 會出現邏輯衝突。  
現行較安全的部分是 **行動已掛在地點下**；風險在節日 `action_extra` 無差別併進當前地點行動池。

**故事原子 = 一張已相容的事態卡**，不是現場拼裝。

### 5.2 一件事需要的因素

| 因素 | 問題 |
|------|------|
| 時段 `slots` | 何時合理？ |
| 地點 `location` | 人在哪？ |
| 行動 `action` | 正在做什麼？ |
| 動機 `motive` | 為何傳給老師？ |
| 允許 `intents` | chat / hook / invite？ |
| 可選節日 | 只加权／改語氣，或使用節日專屬完整 beat |

### 5.3 Beat 資料形狀（示意）

```yaml
beats:
  - id: cafeteria_bento_deny
    slots: [afternoon, evening]
    location: cafeteria
    action: 把剩餘便當推過去卻否認關心
    vibe: 托盤、食材、短暫歇但還盯表
    motive: care_as_cost
    intents: [chat, invite]
    tags: [food, care]

  - id: desk_unsigned_nudge
    slots: [morning, afternoon]
    location: desk
    action: 催簽名欄
    motive: work_hook
    intents: [chat, hook]   # 不開放 invite
    tags: [work, ledger]
```

抽樣：

1. 由預定發送時刻得到 `slot`
2. `beats.filter(slot 符合)`
3. 節日：`tag_boost` / `beat_boost` 或僅選 `observances` 專屬 beat；**注入 tone，不另塞無關行動**
4. 可再乘 storyline 对 location/tags 的权重
5. 抽出整張 beat → 再抽 `intent ∈ beat.intents`
6. 生成一則短訊（模型不得發明其他地點／行動）

### 5.4 Motive 類型（建議）

| motive | 含義 | 典型 intent |
|--------|------|-------------|
| `work_hook` | 帳／簽名／收據 | chat, hook |
| `care_as_cost` | 關心但嘴硬 | chat, invite |
| `transit_bump` | 走廊偶遇式 | chat, hook |
| `wind_down` | 催睡／收尾 | chat, 偶 invite |
| `festive_restraint` | 節日拒鋪張 | chat |

### 5.5 節日

- `tone` → prompt 修飾
- weighted boost，或獨立完整 beat（自帶 location/action/slots）
- **刪除或停用**「任意地點 + action_extra」拼法

### 5.6 第一批 beat 類型（實作時再寫 YAML）

1. 會計位工作鉤 — chat/hook  
2. 會議室碎念 — chat  
3. 夏萊整理 — chat/hook  
4. 走廊短暫離席 — chat/hook  
5. 食堂照顧 — chat/**invite**  
6. 宿舍收尾催睡 — chat／偶 invite  
7. 節日專屬 1～2 張（自帶地點與 slots）

現行 `locations` 可保留當字典；`actions[loc]` 升級為 `beats[]`（或為每條 action 補 slots/motive/intents）。

---

## 6. 主動發訊排程：每天一次、隨機時間

與故事組合分開的排程層：

```text
每日（世界表時區，預設 Asia/Taipei）：
  若今日尚未排程：
    在允許窗內抽一個時刻（建議 09:00–21:00 均勻隨機到分鐘）
    存 next_fire_at、fire_date=今天

Tick（每 1～5 分鐘）：
  無 momotalk_channel_id → skip
  今日已 sent → skip
  now < next_fire_at → skip
  mode == meetup 或 invite pending → 本日順延／取消（實作時二選一，建議：pending 則跳過本日）
  → 依 next_fire_at 的 slot 抽 beat → 發訊 → 標記 sent_date
```

- **一天一則**，不是每 slot 一則  
- 重啟後用已存 `next_fire_at` 恢復，避免重複發或永遠不發  
- `quiet_hours` 可保留；允許窗應避開安靜時段

---

## 7. 流程

### 7.1 開新一局（通過排程閘門後）

1. 抽 beat（規則）  
2. 抽 intent  
3. （可選）薄 ideation → `brief`；MVP 可用 beat 欄位直接組 brief  
4. 產 MomoTalk 短訊（對老師說話；invite 時明確提出碰面）  
5. 寫 session + Discord 發到綁定頻道 + `add_message(assistant)`

Invite 頻率：僅 `intents` 含 invite 的 beat；或再加總體上限（例如主動局約 20%）。

### 7.2 老師回覆（綁定頻道）

1. 寫入 `Message(user)`  
2. 讀 session，組 prompt：人設卡 + brief + 記憶 + 模式規則  
3. LLM 回覆 → 記憶 + 計分  
4. **規則層**更新 session（不交給模型改狀態）：

| 當前 | 老師意圖 | 下一步 |
|------|----------|--------|
| invite pending | 接受 | accepted → mode=meetup |
| invite pending | 拒絕 | declined → 收尾 → idle |
| invite pending | 閒聊 | 保持 pending |
| meetup | 一般 RP | 維持，注入同一 brief |
| meetup | 明確結束 | → idle |
| 過期 | — | 清成 idle |

### 7.3 Meetup

- 同一綁定頻道繼續即可（thread 可選）  
- 每輪強制本局 beat/brief  
- 結束：老師說結束／expires／quiet／管理員 reset → idle，下一曆日才再開主動局

### 7.4 時序總覽

```text
/momotalk here
    → 每日隨機時刻排程
    → 抽 beat → 主動短訊 → 共有記憶
    → 任一路師回覆推進
         ├─ 閒聊
         ├─ 接受 → meetup → 結束 → idle
         └─ 拒絕／過期 → idle
```

---

## 8. Prompt 分層（v2 回合）

```text
[人設卡]                 ← 不動
[本局 beat / brief]      ← session
[lore / storyline 若命中] ← 可選，避免與 beat 搶戲
[記憶摘要 + 最近訊息]     ← 含主動訊息
[/note]
[模式規則：momotalk | meetup | invite pending]
[JSON 輸出格式]
```

MomoTalk 生成約束：必須遵守本局 beat；節日只滲透語氣；禁止發明其他地點／行動。

---

## 9. 建議實作順序（尚未開工）

1. 設定：`momotalk_channel_id` + `/momotalk here|off|status`  
2. 日更一次排程 + 發訊 + 寫記憶（先不做 invite）  
3. Session brief：綁定頻道回覆注入同一 beat  
4. Invite／meetup 狀態機  
5. 事態卡 YAML 與節日改版；ideation 可選  

### MVP 參數草案

- 允許窗：09:00–21:00（時區同 world）  
- `quiet_hours`：維持 `[0, 8]` 或僅作雙重保險  
- 局過期：momotalk 4h；pending invite 2h；meetup 3h（可調）  

---

## 10. 明確不在本草案範圍

- 改寫／加長人設卡劇情  
- 每人獨立 MomoTalk 私串  
- 把本設計接進現行 `sticky_moment` 聊天路徑（應另開分支／模組，避免與現況纏在一起）

---

## 11. 討論結論摘要

1. 人設卡當 identity；故事用事態卡。  
2. 全 guild 一個老師、一條記憶、一份 session。  
3. 主動頻道可配置；未配置不推播。  
4. 每天只發一次，時間隨機但落在合理窗。  
5. 組合要邏輯自洽 → beat 原子化，禁止廁所配吃飯類裸交叉。  
6. 可邀約，老師決定是否赴約。  
7. 現行運作保持不動；本文僅存檔待之後上傳／另開實作。
