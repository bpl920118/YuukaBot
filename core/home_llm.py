"""Detect home / LAN LLM endpoints (localhost or Tailscale) for budget + VRAM."""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

from config import get_settings

logger = logging.getLogger(__name__)

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _host_from_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if host:
        return host
    # bare host:port
    raw = (url or "").strip()
    if "://" not in raw and raw:
        return raw.split("/")[0].split(":")[0].strip().lower()
    return ""


def is_home_inference_url(url: str) -> bool:
    """True for PC-local or Tailscale CGN (100.64/10) or HOME_LLM_HOSTS whitelist."""
    host = _host_from_url(url)
    if not host:
        return False
    if host in _LOOPBACK:
        return True
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback:
            return True
        # Tailscale userspace / CGNAT range
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
        if ip.is_private:
            settings = get_settings()
            if settings.home_llm_trust_private:
                return True
    except ValueError:
        pass
    settings = get_settings()
    allow = {
        h.strip().lower()
        for h in (settings.home_llm_hosts or "").split(",")
        if h.strip()
    }
    return host in allow


def home_api_key_or_placeholder(key: str, base_url: str) -> str:
    """Home backends often need any non-empty Bearer token."""
    text = (key or "").strip()
    if text:
        return text
    if is_home_inference_url(base_url):
        return "local"
    return ""


def should_omit_json_response_format(base_url: str) -> bool:
    """Many local servers reject or ignore response_format=json_object."""
    return is_home_inference_url(base_url)
