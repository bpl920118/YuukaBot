from __future__ import annotations

import base64
import uuid
from pathlib import Path

import httpx

from config import get_settings


class WebuiClient:
    """Call local Automatic1111 / Forge txt2img API."""

    def __init__(self) -> None:
        s = get_settings()
        self.base_url = (s.sd_webui_url or "").rstrip("/")
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

    async def generate(self, *, prompt: str, tier: str, guild_id: int) -> Path | None:
        out_dir = self.image_dir / str(guild_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        if not self.base_url:
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

        url = f"{self.base_url}/sdapi/v1/txt2img"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
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
