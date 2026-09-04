from __future__ import annotations

import base64
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from config import get_settings


def normalize_webui_url(raw: str | None) -> str:
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("網址需為 http:// 或 https:// 開頭，例如 http://100.x.y.z:7860")
    return url


class WebuiClient:
    """Call Automatic1111 / Forge txt2img API (local or Tailscale)."""

    def __init__(self) -> None:
        s = get_settings()
        self.default_url = (s.sd_webui_url or "").rstrip("/")
        self.checkpoint = s.sd_webui_checkpoint
        self.sampler = s.sd_webui_sampler
        self.steps = s.sd_webui_steps
        self.cfg_scale = s.sd_webui_cfg
        self.width = s.sd_webui_width
        self.height = s.sd_webui_height
        self.negative_prompt = s.sd_webui_negative_prompt
        self.timeout = float(s.sd_webui_timeout)
        self.image_dir = Path(s.image_dir)
        self.image_dir.mkdir(parents=True, exist_ok=True)

    def resolve_url(self, override: str | None = None) -> str:
        if override is not None and override.strip():
            return normalize_webui_url(override)
        return (self.default_url or "").rstrip("/")

    async def health(self, *, base_url: str | None = None) -> tuple[bool, str]:
        url = self.resolve_url(base_url)
        if not url:
            return False, "未設定生圖網址（SD_WEBUI_URL / `/image url`）。"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{url}/sdapi/v1/sd-models")
                if resp.status_code == 200:
                    return True, f"可連線：`{url}`"
                return False, f"連上了但狀態碼 {resp.status_code}：`{url}`"
        except Exception as exc:
            return False, f"連線失敗：`{url}`（{type(exc).__name__}: {exc}）"

    async def generate(
        self,
        *,
        prompt: str,
        tier: str,
        guild_id: int,
        base_url: str | None = None,
    ) -> Path | None:
        out_dir = self.image_dir / str(guild_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        resolved = self.resolve_url(base_url)
        if not resolved:
            # Cloud / chat-only: skip generation (no stub files for Discord).
            return None

        steps = self.steps + (4 if tier == "special" else 0)
        payload = {
            "prompt": prompt,
            "negative_prompt": self.negative_prompt,
            "steps": steps,
            "cfg_scale": self.cfg_scale,
            "width": self.width,
            "height": self.height,
            "sampler_name": self.sampler,
            "scheduler": "Automatic",
            "seed": -1,
            "batch_size": 1,
            "n_iter": 1,
            "restore_faces": False,
            "override_settings": {
                "sd_model_checkpoint": self.checkpoint,
            },
            "override_settings_restore_afterwards": True,
        }

        api = f"{resolved}/sdapi/v1/txt2img"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(api, json=payload)
            resp.raise_for_status()
            data = resp.json()

        images = data.get("images") or []
        if not images:
            return None

        raw = images[0]
        if "," in raw[:64]:
            raw = raw.split(",", 1)[1]
        out_path = out_dir / f"{uuid.uuid4().hex}.png"
        out_path.write_bytes(base64.b64decode(raw))
        return out_path
