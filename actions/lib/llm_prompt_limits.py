# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT
"""Prompt size limits for llm_chat_complete (aligned with plan_model-style errors)."""

from __future__ import annotations

from typing import Any

_DEFAULT_MAX_USER = 32768
_DEFAULT_MAX_SYSTEM = 32768
# Prevent absurd config values from blowing memory before encode.
_HARD_CEILING_BYTES = 16 * 1024 * 1024


def _coerce_limit(raw: Any, fallback: int) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return fallback
    return max(1, min(v, _HARD_CEILING_BYTES))


def validate_chat_prompts(
    user_prompt: str,
    system_prompt: str | None,
    cfg: dict[str, Any],
) -> tuple[bool, str | None]:
    """Enforce UTF-8 byte caps and reject NULs before any HTTP or subprocess I/O."""

    if "\x00" in user_prompt:
        return False, "user_prompt must not contain NUL (\\x00) bytes"
    if system_prompt is not None and "\x00" in str(system_prompt):
        return False, "system_prompt must not contain NUL (\\x00) bytes"

    max_user = _coerce_limit(cfg.get("max_user_prompt_bytes"), _DEFAULT_MAX_USER)
    max_sys = _coerce_limit(cfg.get("max_system_prompt_bytes"), _DEFAULT_MAX_SYSTEM)

    u = user_prompt.strip()
    u_bytes = len(u.encode("utf-8"))
    if u_bytes > max_user:
        return (
            False,
            "user_prompt exceeds max UTF-8 byte length (got %d bytes, limit %d)"
            % (u_bytes, max_user),
        )

    if system_prompt is not None and str(system_prompt).strip():
        s = str(system_prompt).strip()
        s_bytes = len(s.encode("utf-8"))
        if s_bytes > max_sys:
            return (
                False,
                "system_prompt exceeds max UTF-8 byte length (got %d bytes, limit %d)"
                % (s_bytes, max_sys),
            )
    return True, None
