# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

"""Structured audit metadata for llm_chat_complete success responses (GAP-6)."""

from __future__ import annotations

from typing import Any


def chat_metadata_http(
    *,
    provider: str,
    model: str,
    tokens_used: int | None,
) -> dict[str, Any]:
    return {
        "access_mode": "http",
        "provider": provider,
        "model": model,
        "tokens_used": tokens_used,
        "exit_code": None,
    }


def chat_metadata_agent_cli(
    *,
    provider: str,
    model: str,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "access_mode": "agent_cli",
        "provider": provider,
        "model": model,
        "tokens_used": None,
        "exit_code": int(exit_code),
    }


def tokens_used_from_openai_payload(payload: dict[str, Any]) -> int | None:
    """Best-effort total tokens from OpenAI-compatible chat.completion JSON."""

    return _tokens_from_openai_usage(payload.get("usage"))


def _tokens_from_openai_usage(usage: Any) -> int | None:
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    if total is not None:
        try:
            return int(total)
        except (TypeError, ValueError):
            pass
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    if pt is not None and ct is not None:
        try:
            return int(pt) + int(ct)
        except (TypeError, ValueError):
            pass
    return None


def tokens_used_from_anthropic_payload(payload: dict[str, Any]) -> int | None:
    """Best-effort total tokens from Anthropic Messages API JSON."""

    return _tokens_from_anthropic_usage(payload.get("usage"))


def _tokens_from_anthropic_usage(usage: Any) -> int | None:
    if not isinstance(usage, dict):
        return None
    it = usage.get("input_tokens")
    ot = usage.get("output_tokens")
    if it is not None and ot is not None:
        try:
            return int(it) + int(ot)
        except (TypeError, ValueError):
            pass
    return None
