#!/usr/bin/env python3
# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT
"""stdin_json_bridge that forwards prompts to OpenCode CLI (`opencode run --format json`).

OpenCode writes one JSON object per line (JSONL) to stdout. Assistant text is taken from
events with ``type == "text"`` and ``part.text``, matching the shape consumed by
Paperclip's ``opencode_local`` adapter (see ``parseOpenCodeJsonl`` in
``@paperclipai/adapter-opencode-local``).

Invocation (tested with OpenCode CLI 1.2.x):

- Binary: resolved from ``OPENCODE_COMMAND``, then ``LLM_PLAN_TASK_OPENCODE_BIN``, else
  ``opencode`` on ``PATH``. Use an absolute path on StackStorm runners when ``PATH`` is
  minimal (same pattern as ``PAPERCLIP_OPENCODE_COMMAND`` in Paperclip deployments).
- Child argv: ``<binary> run --format json --model <model>`` with the combined prompt
  (system + user) as **stdin**, mirroring ``opencode_local`` execute wiring.
- Model: required JSON field ``model`` from the pack; if empty, ``LLM_PLAN_TASK_OPENCODE_MODEL``
  (default ``opencode/gpt-5-nano``) is used.
- ``temperature`` from the stdin JSON protocol is **not** forwarded: ``opencode run`` has
  no stable temperature flag in the tested CLI; adjust provider defaults or wrap with
  a custom argv if your org needs it.

Upstream CLI reference: https://opencode.ai/docs — use ``opencode run --help`` on the
runner to confirm flags for your installed version.

The process must run as the **same POSIX user** that completed OpenCode provider login
(device/OAuth), or a service account that was authenticated once.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _combined_prompt(user_prompt: str, system_prompt: object | None) -> str:
    u = (user_prompt or "").strip()
    sp = system_prompt
    if sp is None or not str(sp).strip():
        return u
    return "%s\n\n%s" % (str(sp).strip(), u)


def _error_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        msg = str(value.get("message", "")).strip()
        if msg:
            return msg
        data = value.get("data")
        if isinstance(data, dict):
            nested = str(data.get("message", "")).strip()
            if nested:
                return nested
        name = str(value.get("name", "")).strip()
        if name:
            return name
        code = str(value.get("code", "")).strip()
        if code:
            return code
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""
    return ""


def _summarize_opencode_stdout(stdout: str) -> tuple[str, str | None]:
    """Extract assistant text and stream errors from OpenCode ``--format json`` stdout."""
    messages: list[str] = []
    errors: list[str] = []

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(event, dict):
            continue

        typ = str(event.get("type", ""))

        if typ == "text":
            part = event.get("part")
            if isinstance(part, dict):
                text = str(part.get("text", "")).strip()
                if text:
                    messages.append(text)
            continue

        if typ == "tool_use":
            part = event.get("part")
            if isinstance(part, dict):
                state = part.get("state")
                if isinstance(state, dict) and str(state.get("status", "")) == "error":
                    err = str(state.get("error", "")).strip()
                    if err:
                        errors.append(err)
            continue

        if typ == "error":
            text = _error_text(event.get("error", event.get("message"))).strip()
            if text:
                errors.append(text)

    summary = "\n\n".join(messages).strip()
    err_msg = "\n".join(errors) if errors else None
    return summary, err_msg


def _resolve_opencode_bin() -> str:
    for key in ("OPENCODE_COMMAND", "LLM_PLAN_TASK_OPENCODE_BIN"):
        v = os.environ.get(key)
        if v and str(v).strip():
            return str(v).strip()
    return "opencode"


def _default_model() -> str:
    v = os.environ.get("LLM_PLAN_TASK_OPENCODE_MODEL")
    if v and str(v).strip():
        return str(v).strip()
    return "opencode/gpt-5-nano"


def main() -> None:
    line = sys.stdin.readline()
    if not line.strip():
        sys.stderr.write("stdin_json_bridge: empty stdin\n")
        sys.exit(2)

    try:
        req = json.loads(line)
    except json.JSONDecodeError as exc:
        sys.stderr.write("stdin_json_bridge: invalid JSON on stdin: %s\n" % exc)
        sys.exit(2)

    if not isinstance(req, dict):
        sys.stderr.write("stdin_json_bridge: stdin JSON must be an object\n")
        sys.exit(2)

    user = req.get("user_prompt")
    if not isinstance(user, str) or not user.strip():
        sys.stderr.write('stdin_json_bridge: missing non-empty "user_prompt"\n')
        sys.exit(2)

    combined = _combined_prompt(user, req.get("system_prompt"))
    model_raw = req.get("model")
    model = str(model_raw).strip() if isinstance(model_raw, str) else ""
    if not model:
        model = _default_model()

    opencode = _resolve_opencode_bin()
    argv = [opencode, "run", "--format", "json", "--model", model]

    cwd_env = os.environ.get("LLM_PLAN_TASK_OPENCODE_CWD")
    cwd = str(cwd_env).strip() if cwd_env and str(cwd_env).strip() else None

    try:
        proc = subprocess.run(
            argv,
            input=(combined + "\n").encode("utf-8"),
            capture_output=True,
            timeout=int(os.environ.get("LLM_PLAN_TASK_OPENCODE_TIMEOUT_SEC", "600")),
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("stdin_json_bridge: OpenCode subprocess timed out\n")
        sys.exit(1)
    except OSError as exc:
        sys.stderr.write("stdin_json_bridge: failed to spawn OpenCode: %s\n" % exc)
        sys.exit(1)

    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace").strip()

    summary, stream_err = _summarize_opencode_stdout(out)

    if proc.returncode != 0:
        msg = "OpenCode exited %s" % proc.returncode
        if err:
            msg = "%s: %s" % (msg, err[:4000])
        elif out.strip():
            msg = "%s: %s" % (msg, out.strip()[:2000])
        sys.stderr.write("%s\n" % msg)
        sys.exit(1)

    if stream_err and not summary:
        sys.stderr.write("%s\n" % stream_err[:4000])
        sys.exit(1)

    if not summary:
        tail = err or out.strip() or "(no stdout)"
        sys.stderr.write(
            "stdin_json_bridge: no assistant text in OpenCode JSON output; stderr/stdout hint: %s\n"
            % tail[:2000]
        )
        sys.exit(1)

    sys.stdout.write(json.dumps({"content": summary}, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
