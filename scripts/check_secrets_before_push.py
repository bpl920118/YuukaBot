"""Fail if staged/tracked paths look like local secrets before push.

Usage (from repo root):
  python scripts/check_secrets_before_push.py
  python scripts/check_secrets_before_push.py --staged
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BLOCK_PATH_RES = [
    re.compile(r"(^|/)\.env$", re.I),
    re.compile(r"(^|/)\.env\.(?!example$)[^/]+$", re.I),
    re.compile(r"\.(pem|key|p12)$", re.I),
    re.compile(r"(^|/)credentials\.json$", re.I),
    re.compile(r"(^|/)yuuka\.db$", re.I),
    re.compile(r"^storage/images/.+", re.I),
]

ALLOW_PATHS = {".env.example", "storage/images/.gitkeep"}

ENV_FILE_HINT = re.compile(r"(^|/)\.env(\.|$)|env\.example$", re.I)
# dotenv lines only — all-caps key, value not code-like
DOTENV_SECRET_RE = re.compile(
    r"(?i)^\s*(?:export\s+)?"
    r"(DISCORD_TOKEN|DEEPSEEK_API_KEY|GEMINI_API_KEY|OPENAI_API_KEY|"
    r"HOME_VRAM_AGENT_TOKEN)\s*=\s*(.+)$"
)
PLACEHOLDER_RE = re.compile(
    r"(?i)^(your_|changeme|replace|xxx|todo|<|local$|dummy|test|none|null|\.\.\.|yuuka-local$)"
)
TOKEN_BODY_RE = re.compile(
    r"(sk-[a-zA-Z0-9]{20,}|AQ\.[A-Za-z0-9_-]{30,}|ghp_[A-Za-z0-9]{20,})"
)


def _git(args: list[str]) -> list[str]:
    out = subprocess.check_output(["git", *args], cwd=ROOT, text=True)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def paths_to_check(*, staged: bool) -> list[str]:
    if staged:
        return _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return _git(["ls-files"])


def _value_looks_real(raw: str) -> bool:
    val = raw.strip().strip("'").strip('"').strip()
    if not val or len(val) < 12:
        return False
    if PLACEHOLDER_RE.search(val):
        return False
    if re.search(r"[()\[\]{}]|settings\.|get_settings|os\.environ", val):
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\.]*", val):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Only check files staged for commit",
    )
    args = parser.parse_args()
    paths = paths_to_check(staged=args.staged)
    bad: list[str] = []

    for rel in paths:
        norm = rel.replace("\\", "/")
        if norm in ALLOW_PATHS:
            continue
        if any(rx.search(norm) for rx in BLOCK_PATH_RES):
            bad.append(f"blocked path: {rel}")
            continue
        file_path = ROOT / rel
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(text) > 400_000:
            continue
        scan_dotenv = bool(ENV_FILE_HINT.search(norm)) or norm.endswith(".example")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if scan_dotenv:
                m = DOTENV_SECRET_RE.match(stripped)
                if m and _value_looks_real(m.group(2)):
                    bad.append(f"{rel}:{i}: secret-like env assignment")
            if "test_" in norm and re.search(r"\bsk-x\b", stripped):
                continue
            if TOKEN_BODY_RE.search(stripped):
                bad.append(f"{rel}:{i}: token-like string")

    if bad:
        print("Secret check FAILED:")
        for item in bad[:50]:
            print(" -", item)
        return 1
    print(
        f"Secret check OK ({len(paths)} paths"
        f"{', staged only' if args.staged else ''}). "
        ".env / images / db stay local-only via .gitignore."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
