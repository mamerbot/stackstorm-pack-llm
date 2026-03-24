# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

import json

import requests

from lib.agent_cli import run_agent_cli
from lib.llm_prompt_limits import validate_chat_prompts
from lib.llm_providers import (
    anthropic_max_tokens,
    build_auth_headers,
    coerce_access_mode,
    coerce_provider,
    default_model_for,
    resolve_api_token,
    resolve_chat_url,
)
from st2actions.runners.pythonrunner import Action


def _effective_call_timeout(cfg: dict, timeout_seconds) -> int:
    """Per-call timeout capped by pack config (GAP-4)."""

    default_cap = 120
    try:
        cap_raw = cfg.get("llm_call_timeout_seconds")
        cap = int(cap_raw) if cap_raw is not None else default_cap
    except (TypeError, ValueError):
        cap = default_cap
    cap = max(1, min(cap, 86400))
    try:
        req = int(timeout_seconds)
    except (TypeError, ValueError):
        req = cap
    req = max(1, min(req, 86400))
    return min(req, cap)


class LlmChatComplete(Action):
    def run(self, user_prompt, system_prompt=None, temperature=0.2, timeout_seconds=60):
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            return False, "user_prompt must be a non-empty string"

        cfg = self.config or {}
        ok_prompt, prompt_err = validate_chat_prompts(user_prompt, system_prompt, cfg)
        if not ok_prompt:
            return False, prompt_err

        effective_timeout = _effective_call_timeout(cfg, timeout_seconds)
        ok_m, mode_or_err = coerce_access_mode(cfg.get("llm_access_mode"))
        if not ok_m:
            return False, mode_or_err
        access_mode = mode_or_err

        ok_p, provider_or_err = coerce_provider(cfg.get("llm_provider"))
        if not ok_p:
            return False, provider_or_err
        provider = provider_or_err

        try:
            temp = float(temperature)
        except (TypeError, ValueError):
            temp = 0.2

        model = (cfg.get("llm_model") or "").strip() or default_model_for(provider)

        if access_mode == "agent_cli":
            return run_agent_cli(
                cfg,
                user_prompt=user_prompt.strip(),
                system_prompt=system_prompt,
                model=model,
                temperature=temp,
                timeout_seconds=effective_timeout,
            )

        url = resolve_chat_url(cfg, provider)
        if not url:
            return (
                False,
                "Pack config llm_chat_completions_url is required for llm_provider=cursor. "
                "Set CURSOR_API_KEY (or api_token) and an OpenAI-compatible chat URL.",
            )

        token = resolve_api_token(cfg, provider)
        headers = build_auth_headers(provider, token, cfg)

        if provider == "anthropic":
            body, parse = self._anthropic_request_body(
                model=model,
                user_prompt=user_prompt.strip(),
                system_prompt=system_prompt,
                temperature=temp,
                cfg=cfg,
            )
        else:
            body, parse = self._openai_compatible_request_body(
                model=model,
                user_prompt=user_prompt.strip(),
                system_prompt=system_prompt,
                temperature=temp,
            )

        try:
            resp = requests.post(
                url,
                headers=headers,
                data=json.dumps(body),
                timeout=effective_timeout,
            )
        except requests.Timeout:
            return False, "LLM HTTP call timed out after %s seconds" % effective_timeout
        except requests.RequestException as exc:
            return False, "HTTP error: %s" % exc

        if resp.status_code < 200 or resp.status_code >= 300:
            return False, "LLM HTTP %s: %s" % (resp.status_code, resp.text[:2000])

        try:
            payload = resp.json()
        except ValueError:
            return False, "Response is not JSON"

        return parse(payload)

    @staticmethod
    def _openai_compatible_request_body(model, user_prompt, system_prompt, temperature):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        body = {
            "model": model,
            "temperature": float(temperature),
            "messages": messages,
        }

        def parse(payload):
            choices = payload.get("choices") or []
            if not choices:
                return False, "LLM response missing choices[]"
            message = choices[0].get("message") or {}
            content = message.get("content")
            if not isinstance(content, str):
                return False, "LLM response missing message.content string"
            return True, {"raw": payload, "content": content.strip()}

        return body, parse

    @staticmethod
    def _anthropic_request_body(model, user_prompt, system_prompt, temperature, cfg):
        messages = [{"role": "user", "content": user_prompt}]
        body = {
            "model": model,
            "max_tokens": anthropic_max_tokens(cfg),
            "messages": messages,
            "temperature": float(temperature),
        }
        if system_prompt:
            body["system"] = system_prompt

        def parse(payload):
            blocks = payload.get("content") or []
            parts = []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            content = "".join(parts).strip()
            if not content:
                return False, "Anthropic response missing text content blocks"
            return True, {"raw": payload, "content": content}

        return body, parse
