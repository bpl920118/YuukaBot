# Local home LLM + SillyTavern (optional)

YuukaBot on **Grok** cannot use `127.0.0.1` on your PC. Use **Tailscale** (same as CG).

Cloud APIs (DeepSeek / Gemini / OpenAI) and Discord `/api` stay fully supported — fill them when you need them. Local models are optional.

## Roles

| Piece | Role |
|-------|------|
| **SillyTavern (ST)** | Local UI to manage character cards / lorebooks, tune against local backend |
| **KoboldCPP / Ollama / LM Studio** | Local OpenAI-compatible inference |
| **YuukaBot (Grok)** | Discord; default cloud API; optional Tailscale → home `/v1` |
| **A1111/Forge** | CG via Tailscale `:7860` |

Do **not** embed ST into Discord. After tuning in ST, copy card text into `characters/` and `git pull` on Grok.

### Character files

| File | Use |
|------|-----|
| `characters/{id}-system-prompt.txt` | Cloud / full card |
| `characters/{id}-system-prompt.local.txt` | Home LLM short card (auto when URL is localhost / Tailscale `100.x`) |
| `characters/{id}.yaml` | Lorebook, storyline, `style_anchor` |
| `characters/{id}-world.yaml` | Locations, schedule, actions, festivals (MomoTalk + sticky scene) |

Sampling (`.env`):

| Var | Default | Use |
|-----|---------|-----|
| `LLM_TEMPERATURE` | `0.85` | Cloud chat |
| `HOME_LLM_TEMPERATURE` | `0.7` | Home Qwen／Kobold chat（穩人設／JSON） |
| `MOMOTALK_TEMPERATURE` | `0.85` | 主動動態（世界表約束；家用略穩） |

Probe: `python scripts/probe_world_momotalk.py`（只抽樣）或加 `--llm`（打本地 Kobold）。

Future: ST PNG/JSON import → these files (not in this release).

## Local backends (pick one; fill URL yourself)

| Backend | ST (local) | Grok bot (Tailscale) |
|---------|------------|----------------------|
| **KoboldCPP** (best ST fit) | `http://127.0.0.1:5001` | `/api url http://100.x.y.z:5001/v1` |
| Ollama | `http://127.0.0.1:11434/v1` | `/api url http://100.x.y.z:11434/v1` |
| LM Studio | `http://127.0.0.1:1234/v1` | `/api url http://100.x.y.z:1234/v1` |

Also set `/api key local` (any non-empty) and `/api model <name>`, then `/api test`.  
Revert: `/api clear`.

### Model suggestion (8GB, 2026)

**Recommended: Qwen3-8B · Q4_K_M**（現世代；人設／指令／摘要優於 2.5）

| Backend | How |
|---------|-----|
| Ollama | `ollama pull qwen3:8b` → model id `qwen3:8b` |
| KoboldCPP | HF [`Qwen/Qwen3-8B-GGUF`](https://huggingface.co/Qwen/Qwen3-8B-GGUF) → `Q4_K_M`（約 5GB 權重） |
| Discord `/api model` | `qwen3:8b` 或 Kobold 載入後顯示的檔名 |

**Notes for YuukaBot / ST**

- Context: natively 32k；8GB 先開 **8k～16k**，長聊靠 bot rolling summary  
- RP：關 thinking／reasoning（bot 家用已 `depth=off`）；ST 也用非思考模式較穩  
- Same GPU + SD：Q4 較有騰顯存空間；勿用 Q8  
- Fallback if OOM / unstable: **Qwen2.5-7B-Instruct Q4**（`qwen2.5:7b`）— 稍舊、稍省 VRAM  

## Modes

**A — Daily (recommended):** Grok `.env` cloud provider. Home PC only for ST card work and/or CG.  
**B — Home model on Discord:** Tailscale online + local server; `/api url` as above. If PC sleeps, `/api clear` back to cloud.

## CG + VRAM

Successful CG replies with **image only** (no text). If SD fails, text reply is kept.

Prefer **VRAM auto-switch** below when Kobold and WebUI share one 8GB GPU.
Without the agent, bot only tries soft Kobold abort (often not enough).

## VRAM auto-switch (8GB same GPU)

Bot calls a **home agent** before/after CG:

| Step | Action |
|------|--------|
| Before txt2img | `POST /switch/sd` → stop Kobold, ensure WebUI `:7860` |
| After txt2img | `POST /switch/llm` → stop WebUI (default), start Kobold |

On the home PC:

1. Double-click `YuukaLocalLLM\start_vram_agent.bat` (keeps running)
2. In bot `.env` (Grok or local):

```env
HOME_VRAM_AGENT_URL=http://127.0.0.1:5010
# or Tailscale: http://100.x.y.z:5010
HOME_VRAM_AGENT_TOKEN=yuuka-local
HOME_VRAM_RELOAD_LLM=true
SD_WEBUI_URL=http://127.0.0.1:7860
# or Tailscale WebUI URL when bot is on Grok
```

Manual test:

```bash
curl -H "Authorization: Bearer yuuka-local" http://127.0.0.1:5010/status
curl -X POST -H "Authorization: Bearer yuuka-local" http://127.0.0.1:5010/switch/sd
curl -X POST -H "Authorization: Bearer yuuka-local" http://127.0.0.1:5010/switch/llm
```

Without the agent, bot still tries soft Kobold abort (often not enough on 8GB).
