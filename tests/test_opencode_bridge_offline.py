# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

"""End-to-end offline tests for contrib OpenCode stdin_json_bridge (no real OpenCode)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "contrib" / "agent_cli" / "example_opencode_bridge.py"


def _write_fake_opencode(tmp_path: Path) -> Path:
    """Executable that mimics ``opencode run --format json`` (one JSONL text line)."""
    exe = tmp_path / "fake_opencode"
    body = """import json
import sys

def main() -> None:
    sys.stdin.read()
    model = "unknown"
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--model" and i + 1 < len(args):
            model = args[i + 1]
            break
    line = json.dumps({"type": "text", "part": {"text": "reply:" + model}})
    sys.stdout.write(line + "\\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
"""
    exe.write_text("#!%s\n%s" % (sys.executable, body), encoding="utf-8")
    exe.chmod(0o755)
    return exe


def _run_bridge(stdin_obj: dict, *, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    payload = (json.dumps(stdin_obj, ensure_ascii=False) + "\n").encode("utf-8")
    return subprocess.run(
        [sys.executable, str(BRIDGE)],
        input=payload,
        capture_output=True,
        env=env,
        check=False,
        cwd=str(ROOT),
        timeout=60,
    )


def _base_env(fake: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "OPENCODE_COMMAND": str(fake),
        "LLM_PLAN_TASK_OPENCODE_TIMEOUT_SEC": "30",
    }


def test_opencode_bridge_happy_path_reports_model_in_argv(tmp_path: Path) -> None:
    fake = _write_fake_opencode(tmp_path)
    env = _base_env(fake)
    proc = _run_bridge(
        {
            "version": "1",
            "user_prompt": "Hello",
            "system_prompt": "You are helpful.",
            "model": "pack/model-x",
            "temperature": 0.2,
        },
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out = json.loads(proc.stdout.decode("utf-8"))
    assert out == {"content": "reply:pack/model-x"}


def test_opencode_bridge_empty_model_uses_llm_plan_task_opencode_model_env(tmp_path: Path) -> None:
    fake = _write_fake_opencode(tmp_path)
    env = _base_env(fake)
    env["LLM_PLAN_TASK_OPENCODE_MODEL"] = "opencode/from-env-fallback"
    proc = _run_bridge(
        {
            "version": "1",
            "user_prompt": "Ping",
            "model": "",
        },
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out = json.loads(proc.stdout.decode("utf-8"))
    assert out == {"content": "reply:opencode/from-env-fallback"}


def test_opencode_bridge_whitespace_only_model_falls_back_to_env(tmp_path: Path) -> None:
    fake = _write_fake_opencode(tmp_path)
    env = _base_env(fake)
    env["LLM_PLAN_TASK_OPENCODE_MODEL"] = "fallback-after-strip"
    proc = _run_bridge(
        {
            "version": "1",
            "user_prompt": "Ping",
            "model": "   ",
        },
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out = json.loads(proc.stdout.decode("utf-8"))
    assert out == {"content": "reply:fallback-after-strip"}
