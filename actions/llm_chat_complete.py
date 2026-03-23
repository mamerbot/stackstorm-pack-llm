# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

import json

import requests

from st2actions.runners.pythonrunner import Action


class LlmChatComplete(Action):
    def run(self, user_prompt, system_prompt=None, temperature=0.2, timeout_seconds=60):
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            return False, "user_prompt must be a non-empty string"

        url = (self.config or {}).get("llm_chat_completions_url")
        token = (self.config or {}).get("api_token")
        model = (self.config or {}).get("llm_model") or "gpt-4o-mini"

        if not url:
            return (
                False,
                "Pack config llm_chat_completions_url is not set. "
                "Install config under /opt/stackstorm/configs/llm_plan_task.yaml",
            )
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer %s" % token

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt.strip()})

        body = {
            "model": model,
            "temperature": float(temperature),
            "messages": messages,
        }

        try:
            resp = requests.post(
                url,
                headers=headers,
                data=json.dumps(body),
                timeout=int(timeout_seconds),
            )
        except requests.RequestException as exc:
            return False, "HTTP error: %s" % exc

        if resp.status_code < 200 or resp.status_code >= 300:
            return False, "LLM HTTP %s: %s" % (resp.status_code, resp.text[:2000])

        try:
            payload = resp.json()
        except ValueError:
            return False, "Response is not JSON"

        choices = payload.get("choices") or []
        if not choices:
            return False, "LLM response missing choices[]"
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            return False, "LLM response missing message.content string"

        return True, {"raw": payload, "content": content.strip()}
