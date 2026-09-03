from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from config import get_settings


class FluxClient:
    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.flux_api_key
        self.base_url = (s.flux_base_url or "").rstrip("/")
        self.model_normal = s.flux_model_normal
        self.model_special = s.flux_model_special
        self.image_dir = Path(s.image_dir)
        self.image_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, *, prompt: str, tier: str, guild_id: int) -> Path | None:
        model = self.model_special if tier == "special" else self.model_normal
        out_dir = self.image_dir / str(guild_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{uuid.uuid4().hex}.webp"

        if not self.api_key or not self.base_url:
            # Stub: write a tiny placeholder text file renamed .webp note for wiring
            note = out_dir / f"{uuid.uuid4().hex}.txt"
            note.write_text(
                f"FLUX stub\nmodel={model}\ntier={tier}\nprompt={prompt}\n",
                encoding="utf-8",
            )
            return note

        # Generic OpenAI-ish images API; adjust when your provider docs arrive
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        url = f"{self.base_url}/v1/images/generations"
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        item = data["data"][0]
        if "b64_json" in item:
            import base64

            out_path.write_bytes(base64.b64decode(item["b64_json"]))
            return out_path
        if "url" in item:
            async with httpx.AsyncClient(timeout=180.0) as client:
                img = await client.get(item["url"])
                img.raise_for_status()
                suffix = ".png"
                ct = img.headers.get("content-type", "")
                if "webp" in ct:
                    suffix = ".webp"
                elif "jpeg" in ct or "jpg" in ct:
                    suffix = ".jpg"
                out_path = out_dir / f"{uuid.uuid4().hex}{suffix}"
                out_path.write_bytes(img.content)
                return out_path
        return None
