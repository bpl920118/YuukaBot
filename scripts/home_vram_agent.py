"""Home-PC VRAM switch agent (stdlib only).

Run on the same machine as KoboldCPP + A1111/Forge.
YuukaBot (local or via Tailscale) calls:
  POST /switch/sd   — free LLM VRAM, ensure WebUI up
  POST /switch/llm  — free/stop SD if needed, ensure Kobold up
  GET  /status
  GET  /health

Auth: Authorization: Bearer <HOME_VRAM_AGENT_TOKEN>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


TOKEN = _env("HOME_VRAM_AGENT_TOKEN", "yuuka-local")
BIND = _env("HOME_VRAM_AGENT_BIND", "127.0.0.1")
PORT = int(_env("HOME_VRAM_AGENT_PORT", "5010") or "5010")
KOBOLD_URL = _env("KOBOLD_URL", "http://127.0.0.1:5001").rstrip("/")
WEBUI_URL = _env("WEBUI_URL", "http://127.0.0.1:7860").rstrip("/")
KOBOLD_DIR = Path(_env("KOBOLD_DIR", r"C:\Users\user\Desktop\YuukaLocalLLM"))
KOBOLD_EXE = Path(_env("KOBOLD_EXE", str(KOBOLD_DIR / "koboldcpp.exe")))
KOBOLD_MODEL = Path(_env("KOBOLD_MODEL", str(KOBOLD_DIR / "Qwen3-8B-Q4_K_M.gguf")))
KOBOLD_ARGS = _env(
    "KOBOLD_ARGS",
    "--gpulayers 999 --contextsize 8192 --port 5001 --usecublas --skiplauncher",
)
WEBUI_BAT = Path(
    _env("WEBUI_BAT", r"C:\Users\user\Desktop\stable-diffusion-webui\webui-user.bat")
)
WEBUI_DIR = Path(_env("WEBUI_DIR", str(WEBUI_BAT.parent)))
STOP_WEBUI_ON_LLM = _env("HOME_VRAM_STOP_WEBUI_ON_LLM", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SD_WAIT_SEC = int(_env("HOME_VRAM_SD_WAIT_SEC", "180") or "180")
LLM_WAIT_SEC = int(_env("HOME_VRAM_LLM_WAIT_SEC", "120") or "120")


def _http_json(method: str, url: str, timeout: float = 8.0) -> tuple[int, object]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return 0, None


def _http_ok(url: str, timeout: float = 5.0) -> bool:
    code, _ = _http_json("GET", url, timeout=timeout)
    return 200 <= code < 300


def kobold_up() -> bool:
    return _http_ok(f"{KOBOLD_URL}/v1/models") or _http_ok(f"{KOBOLD_URL}/api/v1/model")


def webui_up() -> bool:
    return _http_ok(f"{WEBUI_URL}/sdapi/v1/sd-models")


def _win_kill_by_name(names: list[str]) -> list[str]:
    done: list[str] = []
    if sys.platform != "win32":
        return done
    for name in names:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            done.append(name)
        except Exception:
            pass
    return done


def stop_kobold() -> dict:
    notes: list[str] = []
    # Best-effort API shutdown (localhost only on Kobold).
    for path in ("/api/extra/shutdown", "/api/extra/abort"):
        code, _ = _http_json("POST", f"{KOBOLD_URL}{path}", timeout=5.0)
        if code:
            notes.append(f"POST {path} -> {code}")
    time.sleep(1.0)
    killed = _win_kill_by_name(["koboldcpp.exe", "koboldcpp_cu12.exe"])
    if killed:
        notes.append(f"taskkill {killed}")
    # Wait until API is gone
    for _ in range(20):
        if not kobold_up():
            break
        time.sleep(0.5)
    return {"ok": not kobold_up(), "notes": notes, "up": kobold_up()}


def start_kobold() -> dict:
    if kobold_up():
        return {"ok": True, "notes": ["already up"], "up": True}
    if not KOBOLD_EXE.exists():
        return {"ok": False, "notes": [f"missing exe: {KOBOLD_EXE}"], "up": False}
    if not KOBOLD_MODEL.exists():
        return {"ok": False, "notes": [f"missing model: {KOBOLD_MODEL}"], "up": False}
    args = [str(KOBOLD_EXE), "--model", str(KOBOLD_MODEL), *KOBOLD_ARGS.split()]
    notes = [f"launch: {' '.join(args)}"]
    try:
        subprocess.Popen(
            args,
            cwd=str(KOBOLD_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform == "win32" else 0,
        )
    except Exception as exc:
        return {"ok": False, "notes": notes + [str(exc)], "up": False}
    deadline = time.time() + LLM_WAIT_SEC
    while time.time() < deadline:
        if kobold_up():
            return {"ok": True, "notes": notes + ["ready"], "up": True}
        time.sleep(2.0)
    return {"ok": False, "notes": notes + ["timeout waiting for Kobold"], "up": False}


def stop_webui() -> dict:
    notes: list[str] = []
    # Best-effort unload (Forge / some A1111 forks).
    for path in (
        "/sdapi/v1/unload-checkpoint",
        "/sdapi/v1/reload-checkpoint",
    ):
        code, _ = _http_json("POST", f"{WEBUI_URL}{path}", timeout=15.0)
        if code:
            notes.append(f"POST {path} -> {code}")
    if STOP_WEBUI_ON_LLM and sys.platform == "win32":
        try:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'launch_utils|webui.py|stable-diffusion-webui' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            notes.append("stopped webui python via CIM filter")
        except Exception as exc:
            notes.append(f"webui stop skip: {exc}")
        time.sleep(2.0)
    elif not STOP_WEBUI_ON_LLM:
        notes.append("left webui running (HOME_VRAM_STOP_WEBUI_ON_LLM=false)")
    return {"ok": True, "notes": notes, "up": webui_up()}


def start_webui() -> dict:
    if webui_up():
        return {"ok": True, "notes": ["already up"], "up": True}
    if not WEBUI_BAT.exists():
        return {"ok": False, "notes": [f"missing bat: {WEBUI_BAT}"], "up": False}
    notes = [f"launch: {WEBUI_BAT}"]
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(WEBUI_BAT)] if sys.platform == "win32" else [str(WEBUI_BAT)],
            cwd=str(WEBUI_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform == "win32" else 0,
        )
    except Exception as exc:
        return {"ok": False, "notes": notes + [str(exc)], "up": False}
    deadline = time.time() + SD_WAIT_SEC
    while time.time() < deadline:
        if webui_up():
            return {"ok": True, "notes": notes + ["ready"], "up": True}
        time.sleep(3.0)
    return {"ok": False, "notes": notes + ["timeout waiting for WebUI"], "up": False}


def switch_sd() -> dict:
    k = stop_kobold()
    time.sleep(1.5)
    w = start_webui()
    return {
        "mode": "sd",
        "ok": bool(w.get("ok")),
        "kobold": k,
        "webui": w,
        "status": status_payload(),
    }


def switch_llm() -> dict:
    w = stop_webui() if STOP_WEBUI_ON_LLM else {"ok": True, "notes": ["left webui running"], "up": webui_up()}
    time.sleep(1.5)
    k = start_kobold()
    return {
        "mode": "llm",
        "ok": bool(k.get("ok")),
        "webui": w,
        "kobold": k,
        "status": status_payload(),
    }


def status_payload() -> dict:
    return {
        "kobold_up": kobold_up(),
        "webui_up": webui_up(),
        "kobold_url": KOBOLD_URL,
        "webui_url": WEBUI_URL,
        "stop_webui_on_llm": STOP_WEBUI_ON_LLM,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "YuukaVramAgent/1.0"

    def log_message(self, fmt: str, *args) -> None:  # quieter
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Authorization") or ""
        if auth == f"Bearer {TOKEN}":
            return True
        # Also accept ?token= for quick local curl
        from urllib.parse import urlparse, parse_qs

        qs = parse_qs(urlparse(self.path).query)
        return (qs.get("token") or [None])[0] == TOKEN

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send(200, {"ok": True})
            return
        if path == "/status":
            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            self._send(200, {"ok": True, **status_payload()})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not self._auth_ok():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        if path == "/switch/sd":
            self._send(200, switch_sd())
            return
        if path == "/switch/llm":
            self._send(200, switch_llm())
            return
        self._send(404, {"ok": False, "error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(
        f"Yuuka VRAM agent on http://{BIND}:{PORT} "
        f"(kobold={KOBOLD_URL}, webui={WEBUI_URL})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("bye", flush=True)


if __name__ == "__main__":
    main()
