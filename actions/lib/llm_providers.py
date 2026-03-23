# Copyright 2026 Emtesseract / Paperclip contributors
# SPDX-License-Identifier: MIT

"""LLM provider defaults: env-based API keys and HTTP shapes for chat-style calls."""

from __future__ import annotations

import base64
import os
from typing import Any

DEFAULT_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"

_PROVIDERS = frozenset({"openai", "anthropic", "cursor"})

_ACCESS_MODES = frozenset({"http", "agent_cli"})

_DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "cursor": "gpt-4o-mini",
}

_ENV_KEY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "cursor": "CURSOR_API_KEY",
}


def coerce_access_mode(raw: Any) -> tuple[bool, str]:
    """Return (True, mode) or (False, error_message). Default http."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return True, "http"
    s = str(raw).strip().lower()
    if s not in _ACCESS_MODES:
        return False, "llm_access_mode must be one of: http, agent_cli"
    return True, s


def coerce_provider(raw: Any) -> tuple[bool, str]:
    """Return (True, provider) or (False, error_message)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return True, "openai"
    s = str(raw).strip().lower()
    if s not in _PROVIDERS:
        return False, "llm_provider must be one of: openai, anthropic, cursor"
    return True, s


def default_model_for(provider: str) -> str:
    return _DEFAULT_MODEL.get(provider, _DEFAULT_MODEL["openai"])


def resolve_api_token(cfg: dict[str, Any] | None, provider: str) -> str | None:
    explicit = (cfg or {}).get("api_token")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    var = _ENV_KEY.get(provider)
    if not var:
        return None
    val = os.environ.get(var)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def resolve_chat_url(cfg: dict[str, Any] | None, provider: str) -> str | None:
    url = (cfg or {}).get("llm_chat_completions_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    if provider == "openai":
        return DEFAULT_OPENAI_CHAT_URL
    if provider == "anthropic":
        return DEFAULT_ANTHROPIC_MESSAGES_URL
    return None


def build_auth_headers(
    provider: str,
    token: str | None,
    cfg: dict[str, Any] | None,
) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if not token:
        return headers
    if provider == "anthropic":
        headers["x-api-key"] = token
        headers["anthropic-version"] = "2023-06-01"
        return headers
    cfg = cfg or {}
    if provider == "cursor" and cfg.get("cursor_api_basic_auth") is True:
        basic = base64.b64encode(("%s:" % token).encode("utf-8")).decode("ascii")
        headers["Authorization"] = "Basic %s" % basic
        return headers
    headers["Authorization"] = "Bearer %s" % token
    return headers


def anthropic_max_tokens(cfg: dict[str, Any] | None) -> int:
    raw = (cfg or {}).get("llm_max_tokens")
    if raw is None:
        return 4096
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 4096
    return max(1, min(n, 200_000))
