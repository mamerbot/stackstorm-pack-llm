# Agent CLI bridges for `llm_access_mode: agent_cli`

These files are **not** loaded by StackStorm automatically. Copy a script to a path on
your action runner (for example `/opt/stackstorm/scripts/`) and point
`agent_cli_executable` or `agent_cli_argv_json` at it.

## Stdin JSON protocol (`stdin_json_bridge`)

The pack writes **one UTF-8 JSON object** on stdin, followed by a newline:

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | string | Currently `1` |
| `user_prompt` | string | Required user message |
| `system_prompt` | string or null | Optional system instructions |
| `model` | string | From pack `llm_model` (hint for the bridge) |
| `temperature` | number | From action parameter |

Stdout must be a **single JSON object** with a string field **`content`** (assistant
reply). The action returns `{"raw": <parsed stdout>, "content": ...}` to match the HTTP path.

## Example: minimal echo bridge (testing only)

`example_echo_bridge.py` — returns a fixed string; useful to verify StackStorm wiring.

## Example: OpenCode (`opencode run --format json`)

`example_opencode_bridge.py` — copy-paste reference for **OpenCode** behind
`agent_cli_profile: stdin_json_bridge`. It reads the stdin JSON line, combines
`system_prompt` + `user_prompt`, runs `opencode run --format json --model …` with that
text on the child’s stdin, parses JSONL stdout (assistant `type: "text"` events), and
prints `{"content": "…"}`.

Environment knobs:

| Variable | Purpose |
| --- | --- |
| `OPENCODE_COMMAND` | Preferred path to the OpenCode binary (same idea as Paperclip’s `PAPERCLIP_OPENCODE_COMMAND`). |
| `LLM_PLAN_TASK_OPENCODE_BIN` | Fallback if `OPENCODE_COMMAND` is unset. |
| `LLM_PLAN_TASK_OPENCODE_MODEL` | Default model when the stdin JSON `model` field is empty (default `opencode/gpt-5-nano`). |
| `LLM_PLAN_TASK_OPENCODE_CWD` | Optional working directory for the OpenCode process. |
| `LLM_PLAN_TASK_OPENCODE_TIMEOUT_SEC` | Subprocess timeout in seconds (default `600`). |

Run the script as the **same POSIX user** that completed OpenCode provider auth on the
runner (or a dedicated service account that was logged in once).

## Wiring Cursor, Codex, OpenCode

Vendor CLIs change flags between releases. Recommended pattern:

1. Set `llm_access_mode: agent_cli` and `agent_cli_profile: stdin_json_bridge`.
2. Implement `agent_cli_executable` as a small script that:
   - `json.loads(sys.stdin.readline())`
   - builds the prompt from `system_prompt` + `user_prompt`
   - invokes **your** pinned `cursor`, `codex`, or `opencode` command with the flags
     your org standardizes (or start from `example_opencode_bridge.py` for OpenCode)
   - prints `json.dumps({"content": assistant_text})`

Run that script as the **same POSIX user** that owns the agent login/session (or use a
service account that performed device/OAuth login once).

## `claude_code` profile

If you use the built-in `claude_code` profile, you do **not** need a bridge script: the
pack invokes `claude -p … --output-format=json --bare` directly. You still need Claude
Code installed and authenticated on the runner.
