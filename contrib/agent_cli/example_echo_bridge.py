#!/usr/bin/env python3
# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT
"""Tiny stdin_json_bridge for wiring tests — replace with a real vendor wrapper."""

from __future__ import annotations

import json
import sys


def main() -> None:
    line = sys.stdin.readline()
    req = json.loads(line)
    _ = req.get("version")
    user = req.get("user_prompt") or ""
    sys_p = req.get("system_prompt")
    combined = user if not sys_p else "%s\n\n%s" % (sys_p, user)
    out = {"content": "echo:%s" % combined[:200]}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
