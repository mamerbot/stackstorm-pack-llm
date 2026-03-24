# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

"""Invoke a coding-agent CLI or operator bridge instead of raw HTTP API keys."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from typing import Any

_STDIN_JSON_VERSION = "1"

_DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
_HARD_CEILING_RESPONSE_BYTES = 16 * 1024 * 1024

_PROFILES = frozenset({"stdin_json_bridge", "claude_code", "custom"})

_CTX_KEYS = (
    "combined_prompt",
    "user_prompt",
    "system_prompt",
    "model",
    "temperature",
)

_STDOUT_KINDS = frozenset({"json_content", "claude_code_result", "raw_text"})


def agent_cli_allowed_executable_prefix(cfg: dict[str, Any]) -> str | None:
    raw = cfg.get("agent_cli_allowed_executable_prefix")
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def resolve_validated_cli_path(
    raw: str,
    *,
    field_label: str,
    allowed_prefix: str | None,
) -> tuple[bool, str]:
    """Resolve argv0 to realpath; require regular executable; optional allowed-prefix check."""

    s = str(raw).strip()
    if not s:
        return False, "%s must be a non-empty string" % field_label

    candidate = s
    if not os.path.isabs(candidate):
        found = shutil.which(candidate)
        if not found:
            return (
                False,
                "%s must be an absolute path to an existing executable "
                "(got %r; not found on PATH)" % (field_label, raw),
            )
        candidate = found

    try:
        real = os.path.realpath(candidate)
    except OSError as exc:
        return False, "%s path could not be resolved (%s): %s" % (field_label, candidate, exc)

    try:
        st = os.stat(real)
    except OSError as exc:
        return (
            False,
            "%s path does not exist or is not accessible (%s): %s" % (field_label, real, exc),
        )

    if not stat.S_ISREG(st.st_mode):
        return False, "%s must be a regular file (got %s)" % (field_label, real)

    if not os.access(real, os.X_OK):
        return False, "%s must be executable (got %s)" % (field_label, real)

    if allowed_prefix:
        try:
            prefix_real = os.path.realpath(allowed_prefix)
        except OSError as exc:
            return (
                False,
                "agent_cli_allowed_executable_prefix could not be resolved (%s): %s"
                % (allowed_prefix, exc),
            )
        if real != prefix_real and not real.startswith(prefix_real + os.sep):
            return (
                False,
                "%s (%s) is outside agent_cli_allowed_executable_prefix (%s)"
                % (field_label, real, prefix_real),
            )

    return True, real


def coerce_agent_cli_profile(raw: Any) -> tuple[bool, str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return False, "agent_cli_profile is required when llm_access_mode=agent_cli"
    s = str(raw).strip().lower()
    if s not in _PROFILES:
        return (
            False,
            "agent_cli_profile must be one of: stdin_json_bridge, claude_code, custom",
        )
    return True, s


def coerce_stdout_kind(raw: Any, profile: str) -> tuple[bool, str]:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        if profile == "stdin_json_bridge":
            return True, "json_content"
        if profile == "claude_code":
            return True, "claude_code_result"
        return True, "raw_text"
    s = str(raw).strip().lower()
    if s not in _STDOUT_KINDS:
        return (
            False,
            "agent_cli_stdout_kind must be one of: json_content, claude_code_result, raw_text",
        )
    return True, s


def combined_prompt(user_prompt: str, system_prompt: str | None) -> str:
    u = user_prompt.strip()
    if not system_prompt or not str(system_prompt).strip():
        return u
    return "%s\n\n%s" % (str(system_prompt).strip(), u)


def _coerce_max_response_bytes(raw: Any) -> int:
    """Upper bound on stdin_json_bridge raw stdout before JSON parse (GAP-7)."""

    if raw is None:
        return _DEFAULT_MAX_RESPONSE_BYTES
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_RESPONSE_BYTES
    return max(1, min(v, _HARD_CEILING_RESPONSE_BYTES))


def _template_segment_used_substitution(segment: str) -> bool:
    for k in _CTX_KEYS:
        if "{%s}" % k in segment:
            return True
    return False


def _validate_custom_argv_after_substitution(segment: str) -> tuple[bool, str]:
    """Reject NUL/newlines and argv token injection via expanded placeholders (GAP-3)."""

    if "\x00" in segment:
        return False, "custom argv contains NUL after placeholder substitution"
    if "\n" in segment or "\r" in segment:
        return (
            False,
            "custom argv contains newline after placeholder substitution",
        )
    stripped = segment.strip()
    if stripped.startswith("-"):
        return (
            False,
            "custom argv placeholder expansion must not start with '-' (got %r)" % (segment[:120],),
        )
    return True, ""


def _substitute_argv(
    template: list[str],
    *,
    combined: str,
    user_prompt: str,
    system_prompt: str | None,
    model: str,
    temperature: float,
) -> tuple[bool, str | list[str]]:
    ctx = {
        "combined_prompt": combined,
        "user_prompt": user_prompt,
        "system_prompt": system_prompt or "",
        "model": model,
        "temperature": str(temperature),
    }
    out: list[str] = []
    for part in template:
        s0 = str(part)
        had_ph = _template_segment_used_substitution(s0)
        s = s0
        for k, v in ctx.items():
            s = s.replace("{%s}" % k, v)
        if had_ph:
            ok_v, err = _validate_custom_argv_after_substitution(s)
            if not ok_v:
                return False, err
        out.append(s)
    return True, out


def _parse_stdout_payload(stdout: str, kind: str) -> tuple[bool, Any]:
    text = stdout.strip()
    if kind == "raw_text":
        if not text:
            return False, "agent CLI produced empty stdout"
        return True, {"content": text, "raw": text}

    try:
        payload = json.loads(text)
    except ValueError as exc:
        return False, "agent CLI stdout is not valid JSON: %s" % exc

    if kind == "json_content":
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            return False, 'JSON stdout missing non-empty string field "content"'
        return True, {"content": content.strip(), "raw": payload}

    if kind == "claude_code_result":
        content = payload.get("result")
        if not isinstance(content, str) or not content.strip():
            return False, 'Claude Code JSON stdout missing non-empty string field "result"'
        return True, {"content": content.strip(), "raw": payload}

    return False, "unknown agent_cli_stdout_kind"


def parse_custom_argv_json(raw: Any) -> tuple[bool, str | list[str]]:
    if raw is None:
        return False, "agent_cli_argv_json is required when agent_cli_profile=custom"
    if isinstance(raw, list):
        if not raw:
            return False, "agent_cli_argv_json must be a non-empty JSON array"
        try:
            return True, [str(x) for x in raw]
        except (TypeError, ValueError):
            return False, "agent_cli_argv_json list entries must be strings"
    if not isinstance(raw, str) or not raw.strip():
        return False, "agent_cli_argv_json is required when agent_cli_profile=custom"
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return False, "agent_cli_argv_json must be valid JSON: %s" % exc
    if not isinstance(data, list) or not data:
        return False, "agent_cli_argv_json must be a non-empty JSON array"
    try:
        return True, [str(x) for x in data]
    except (TypeError, ValueError):
        return False, "agent_cli_argv_json array entries must be strings"


def run_agent_cli(
    cfg: dict[str, Any],
    *,
    user_prompt: str,
    system_prompt: str | None,
    model: str,
    temperature: float,
    timeout_seconds: int,
) -> tuple[bool, str | dict[str, Any]]:
    ok_p, profile_or_err = coerce_agent_cli_profile(cfg.get("agent_cli_profile"))
    if not ok_p:
        return False, profile_or_err
    profile = profile_or_err

    ok_k, kind_or_err = coerce_stdout_kind(cfg.get("agent_cli_stdout_kind"), profile)
    if not ok_k:
        return False, kind_or_err
    stdout_kind = kind_or_err

    cwd = cfg.get("agent_cli_working_directory")
    if cwd is not None and (not isinstance(cwd, str) or not cwd.strip()):
        cwd = None
    elif isinstance(cwd, str):
        cwd = cwd.strip()

    combined = combined_prompt(user_prompt, system_prompt)
    prefix = agent_cli_allowed_executable_prefix(cfg)

    if profile == "stdin_json_bridge":
        exe = cfg.get("agent_cli_executable")
        if not isinstance(exe, str) or not exe.strip():
            return (
                False,
                "agent_cli_executable is required when agent_cli_profile=stdin_json_bridge",
            )
        ok_path, path_or_err = resolve_validated_cli_path(
            exe.strip(),
            field_label="agent_cli_executable",
            allowed_prefix=prefix,
        )
        if not ok_path:
            return False, path_or_err
        argv = [path_or_err]
        stdin_obj = {
            "version": _STDIN_JSON_VERSION,
            "user_prompt": user_prompt.strip(),
            "system_prompt": (system_prompt or "").strip() or None,
            "model": model,
            "temperature": float(temperature),
        }
        stdin_bytes = (json.dumps(stdin_obj, ensure_ascii=False) + "\n").encode("utf-8")
    elif profile == "claude_code":
        binary = cfg.get("agent_cli_binary")
        if not isinstance(binary, str) or not binary.strip():
            binary = "claude"
        else:
            binary = binary.strip()
        ok_path, path_or_err = resolve_validated_cli_path(
            binary,
            field_label="agent_cli_binary",
            allowed_prefix=prefix,
        )
        if not ok_path:
            return False, path_or_err
        argv = [
            path_or_err,
            "-p",
            combined,
            "--output-format",
            "json",
            "--bare",
        ]
        stdin_bytes = None
    else:
        ok_a, tpl_or_err = parse_custom_argv_json(cfg.get("agent_cli_argv_json"))
        if not ok_a:
            return False, tpl_or_err
        ok_sub, argv_or_err = _substitute_argv(
            tpl_or_err,
            combined=combined,
            user_prompt=user_prompt.strip(),
            system_prompt=system_prompt,
            model=model,
            temperature=float(temperature),
        )
        if not ok_sub:
            return False, argv_or_err
        argv = argv_or_err
        if not argv:
            return False, "agent_cli_argv_json must expand to a non-empty argv"
        ok_path, path_or_err = resolve_validated_cli_path(
            argv[0],
            field_label="agent_cli_argv_json executable (first argv element)",
            allowed_prefix=prefix,
        )
        if not ok_path:
            return False, path_or_err
        argv[0] = path_or_err
        stdin_bytes = None

    try:
        proc = subprocess.run(
            argv,
            input=stdin_bytes,
            capture_output=True,
            timeout=int(timeout_seconds),
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "agent CLI timed out after %s seconds" % int(timeout_seconds)
    except OSError as exc:
        return False, "failed to spawn agent CLI: %s" % exc

    raw_out = proc.stdout
    if not isinstance(raw_out, (bytes, bytearray)):
        raw_out = b""

    if profile == "stdin_json_bridge" and stdout_kind == "json_content":
        limit = _coerce_max_response_bytes(cfg.get("max_response_bytes"))
        if len(raw_out) > limit:
            return (
                False,
                "stdin_json_bridge stdout exceeds max_response_bytes "
                "(got %d bytes, limit %d)" % (len(raw_out), limit),
            )

    out = bytes(raw_out).decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        msg = "agent CLI exited %s" % proc.returncode
        if err:
            msg = "%s: %s" % (msg, err[:2000])
        elif out.strip():
            msg = "%s: %s" % (msg, out.strip()[:2000])
        return False, msg

    ok, parsed_or_err = _parse_stdout_payload(out, stdout_kind)
    if not ok:
        hint = ""
        if err:
            hint = " (stderr: %s)" % err[:500]
        return False, "%s%s" % (parsed_or_err, hint)

    if isinstance(parsed_or_err, dict):
        parsed_or_err["agent_exit_code"] = int(proc.returncode)
    return True, parsed_or_err
