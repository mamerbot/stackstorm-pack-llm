# StackStorm pack: `llm_plan_task`

Actions and an Orquesta workflow for **LLM-assisted planning** and **task decomposition** inside StackStorm.

**Source repository:** [github.com/mamerbot/stackstorm-pack-llm](https://github.com/mamerbot/stackstorm-pack-llm)

## Layout

- `pack.yaml` — pack metadata
- `config.schema.yaml` — optional settings for `llm_chat_complete` (HTTP provider keys or `agent_cli` subprocess bridge)
- `actions/` — python-script actions + `workflows/plan_to_tasks.yaml`
- `tests/` — off-box unit tests for the pure plan helpers

## Actions

| Action | Purpose |
| --- | --- |
| `plan_from_goal` | Build a normalized plan from a goal; optionally merge validated JSON from an LLM. |
| `normalize_plan_from_llm` | Parse/validate raw LLM output (including ```json fences) into a plan object. |
| `tasks_from_plan` | Expand a validated plan into pending tasks with stable ids and dependency edges. |
| `llm_chat_complete` | Chat via pack config: `llm_access_mode` `http` (OpenAI-compatible `openai`/`cursor`, Anthropic `anthropic`, env API keys) or `agent_cli` (spawn Claude Code / custom argv / stdin JSON bridge on the runner). |
| `plan_to_tasks` | Orquesta workflow chaining `plan_from_goal` → `tasks_from_plan`. |

## `plan_to_tasks` workflow — failure context

On validation or expansion errors, `plan_from_goal` and `tasks_from_plan` return `(False, message)`; StackStorm marks the action failed. The workflow matches `when: <% failed() %>`, **publishes** a stable diagnostic shape into context and workflow **output**, then runs `core.fail` with `failure_message` so the overall workflow execution is clearly **failed** in `st2 execution list` while automation can still read structured fields from the workflow result.

| Field | Type | Meaning |
| --- | --- | --- |
| `failure_stage` | string | `plan` — `plan_from_goal` failed; `derive_tasks` — `tasks_from_plan` failed. |
| `failure_message` | string | Human-readable error (typically the tuple’s second element from the Python runner). |
| `failure_raw` | object | Full action result object for the failing step (runner-specific keys such as `result`, `stdout`, `stderr`; use for deep debugging). |

On success these are omitted (null in workflow output). The success **`bundle`** contract is unchanged.

## Task bundle shape (`tasks_from_plan` / `plan_to_tasks`)

The action return value (and workflow-published `bundle`) includes:

| Field | Type | Meaning |
| --- | --- | --- |
| `plan` | object | Normalized plan (same schema as validated input). |
| `tasks` | array | Pending tasks in **plan step list order** (one entry per step). |
| `execution_order` | string[] | Task ids (`task-<step_id>`) in a **dependency-safe topological order** (Kahn). Any prerequisite in `depends_on` appears before dependents. When several tasks are ready at once, order follows **plan step list order**, then **task id** lexicographically, so the sort is stable and deterministic even if step rows are reordered in JSON. |
| `run_id` | string | UUID for this expansion run. |

Downstream runners should iterate `execution_order` (or schedule by it) when executing `action_ref` / `action_parameters`, not assume `tasks` array order matches execution safety.

The **`execution_order`** field is a **dependency-safe topological ordering** of task ids: every entry in a task’s `depends_on` appears earlier in `execution_order` than that task. When multiple tasks are ready, tie-break order follows **plan step list order**, then **task id** lexicographically (see [EMT-70](/EMT/issues/EMT-70) and `_execution_order_for_tasks` in `actions/lib/plan_model.py`). Consumers should validate bundles when crossing process boundaries; runtime validation in StackStorm may be added separately (e.g. [EMT-74](/EMT/issues/EMT-74)).

## Task bundle JSON schema (v1)

Machine-readable contract: [`schemas/task_bundle.v1.json`](schemas/task_bundle.v1.json) (JSON Schema draft 2020-12). It describes the bundle root (`plan`, `tasks`, `execution_order`, `run_id`) and each **expanded task** (`id`, `step_id`, `title`, `description`, `depends_on`, `status`, optional `action_ref` / `action_parameters`). The embedded **`plan`** object is not duplicated in full: the schema types it as an object and documents that it **must** also satisfy [`schemas/plan.v1.json`](schemas/plan.v1.json). Helpers apply both layers:

- **`validate_task_bundle()`** in `actions/lib/plan_model.py` runs JSON Schema for the bundle, then `validate_plan(bundle["plan"])`, then **Python-only** checks (task rows mirror `plan["steps"]` in order and fields, `execution_order` is exactly the Kahn order produced by `_execution_order_for_tasks`, `run_id` is a UUID string).

Golden examples under [`tests/fixtures/bundle_*.json`](tests/fixtures/) are validated in CI by `tests/test_task_bundle_fixtures.py` (jsonschema + `validate_task_bundle`), alongside the existing plan fixture tests.

## Plan JSON schema (v1)

Machine-readable contract: [`schemas/plan.v1.json`](schemas/plan.v1.json) (JSON Schema draft 2020-12). It matches the structural rules enforced by `validate_plan` in `actions/lib/plan_model.py`. **Caps** on string lengths, step counts, `action_parameters` nesting/size, and **dependency graph** checks (known step ids, acyclic `depends_on`) are enforced in Python only; the schema documents that split in its root `description`.

Golden examples under [`tests/fixtures/`](tests/fixtures/) are validated in CI by `tests/test_schema_fixtures.py` using the `jsonschema` library, and each fixture is also run through `validate_plan` for parity.

```json
{
  "version": "1",
  "goal": "string",
  "assumptions": ["string"],
  "risks": ["string"],
  "steps": [
    {
      "id": "string",
      "title": "string",
      "description": "string",
      "depends_on": ["other-step-id"],
      "action_ref": "pack.action",
      "action_parameters": { "key": "value" }
    }
  ]
}
```

Optional per-step **`action_ref`** binds a StackStorm action to that step. When present after validation, it must be a non-empty string matching **`pack.action`**: exactly one dot, with both sides non-empty tokens using only ASCII letters, digits, and underscores (for example `core.local`, `my_pack.run_job`). Empty or whitespace-only values are treated as absent. Validated plans **omit** the `action_ref` key on steps that do not specify one; when set, the same key is copied onto the expanded task objects from `tasks_from_plan` / `plan_to_tasks`.

Optional per-step **`action_parameters`** is a JSON **object** (Python `dict`) of parameters for the bound StackStorm action. It may only appear when **`action_ref`** is present and non-empty after normalization; plans that set `action_parameters` without a bound action are rejected. The key is omitted on normalized steps and expanded tasks when not provided (same convention as `action_ref`). Values must be JSON-serializable (`null`, booleans, numbers, strings, arrays, nested objects).

**`action_parameters` bounds** (module-level constants in `actions/lib/plan_model.py`):

| Constant | Limit |
| --- | --- |
| `MAX_ACTION_PARAMETERS_UTF8_BYTES` | 8192 UTF-8 bytes of canonical `json.dumps` output (sorted keys, compact separators) |
| `MAX_ACTION_PARAMETERS_NESTING_DEPTH` | 16 nested container levels (objects/arrays) from the root object |
| `MAX_ACTION_PARAMETERS_KEYS_PER_OBJECT` | 64 keys per object |
| `MAX_ACTION_PARAMETERS_ARRAY_LENGTH` | 64 elements per array |

Validation rejects pathologically large plans before task expansion. Other caps in `plan_model.py` include: max step count, max `goal` length, per-step limits on `id` / `title` / `description` / `action_ref` length / `depends_on` entry count and dependency id length, and limits on `assumptions` / `risks` list size and string length. Oversized input raises `PlanValidationError` with a message naming the field and the limit.

## Install (StackStorm)

```bash
git clone https://github.com/mamerbot/stackstorm-pack-llm.git llm_plan_task
cd llm_plan_task
st2 pack install file://$PWD
```

Copy `llm_plan_task.yaml.example` to `/opt/stackstorm/configs/llm_plan_task.yaml`, adjust URLs/tokens, then:

```bash
sudo st2ctl reload --register-configs
```

## Usage examples

Successful **python-script** actions return `(True, payload)`; in API/CLI output the payload is typically nested as **`result.result`** (see `st2 execution get <id> -j`). The JSON below matches that payload shape. Values such as **`run_id`** are UUIDs and differ on each run unless noted.

### `plan_from_goal` (template mode)

No `structured_plan_json` → deterministic template plan for wiring and tests.

```bash
st2 run llm_plan_task.plan_from_goal goal="Roll out monitoring"
```

**Example result** (`result.result`):

```json
{
  "version": "1",
  "goal": "Roll out monitoring",
  "assumptions": [
    "Template mode: replace this plan with model output by passing structured_plan_json."
  ],
  "risks": [],
  "steps": [
    {
      "id": "clarify",
      "title": "Clarify requirements and success criteria",
      "description": "Confirm scope, constraints, and acceptance checks for: Roll out monitoring",
      "depends_on": []
    },
    {
      "id": "design",
      "title": "Design approach",
      "description": "Outline an implementation or operational approach.",
      "depends_on": ["clarify"]
    },
    {
      "id": "execute",
      "title": "Execute primary work",
      "description": "Carry out the planned steps with traceable outputs.",
      "depends_on": ["design"]
    },
    {
      "id": "verify",
      "title": "Verify and document",
      "description": "Validate results and capture what changed for operators.",
      "depends_on": ["execute"]
    }
  ]
}
```

### `plan_from_goal` (with `structured_plan_json`)

Pass validated plan JSON from an LLM or file. With default `override_goal=true`, the CLI `goal=` replaces `plan.goal` after validation.

```bash
st2 run llm_plan_task.plan_from_goal \
  goal="Roll out monitoring with LLM JSON" \
  structured_plan_json='{"version":"1","goal":"From JSON only","assumptions":[],"risks":[],"steps":[{"id":"a","title":"A","description":"d","depends_on":[]},{"id":"b","title":"B","description":"d2","depends_on":["a"]}]}'
```

**Example result** (`result.result`):

```json
{
  "version": "1",
  "goal": "Roll out monitoring with LLM JSON",
  "steps": [
    {
      "id": "a",
      "title": "A",
      "description": "d",
      "depends_on": []
    },
    {
      "id": "b",
      "title": "B",
      "description": "d2",
      "depends_on": ["a"]
    }
  ],
  "assumptions": [],
  "risks": []
}
```

### `normalize_plan_from_llm`

Accepts raw model text: optional **` ```json `** … **` ``` `** fences are stripped when the trimmed string starts with a fence; otherwise the whole string must be JSON.

**Example (markdown fences):**

```bash
st2 run llm_plan_task.normalize_plan_from_llm plan_json_str='```json
{
  "version": "1",
  "goal": "Ship patch release",
  "assumptions": [],
  "risks": [],
  "steps": [
    {"id": "prep", "title": "Prepare change", "description": "", "depends_on": []},
    {"id": "ship", "title": "Ship", "description": "", "depends_on": ["prep"]}
  ]
}
```'
```

**Example result** (`result.result`):

```json
{
  "version": "1",
  "goal": "Ship patch release",
  "assumptions": [],
  "risks": [],
  "steps": [
    {
      "id": "prep",
      "title": "Prepare change",
      "description": "",
      "depends_on": []
    },
    {
      "id": "ship",
      "title": "Ship",
      "description": "",
      "depends_on": ["prep"]
    }
  ]
}
```

### `tasks_from_plan`

`plan` is a JSON object (same schema as `plan_from_goal` output).

```bash
st2 run llm_plan_task.tasks_from_plan \
  plan='{"version":"1","goal":"One-step demo","assumptions":[],"risks":[],"steps":[{"id":"only","title":"Single step","description":"","depends_on":[]}]}'
```

**Example result** (`result.result`). The `run_id` is a new UUID each execution; the value below is illustrative.

```json
{
  "plan": {
    "version": "1",
    "goal": "One-step demo",
    "steps": [
      {
        "id": "only",
        "title": "Single step",
        "description": "",
        "depends_on": []
      }
    ],
    "assumptions": [],
    "risks": []
  },
  "tasks": [
    {
      "id": "task-only",
      "step_id": "only",
      "title": "Single step",
      "description": "",
      "depends_on": [],
      "status": "pending"
    }
  ],
  "execution_order": ["task-only"],
  "run_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
}
```

### `llm_chat_complete`

#### HTTP access (`llm_access_mode: http`, default)

Set `llm_provider` to `openai` (default), `anthropic`, or `cursor`. Use `api_token` or the matching environment variable on the StackStorm action runner: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `CURSOR_API_KEY`. `llm_chat_completions_url` defaults for OpenAI and Anthropic; **cursor** requires an explicit OpenAI-compatible URL (see `llm_plan_task.yaml.example`). Optional: `cursor_api_basic_auth`, `llm_max_tokens` (Anthropic).

#### Agent / ACP-style access (`llm_access_mode: agent_cli`)

Use this when the **model should authenticate like a coding agent** (interactive CLI OAuth/session, corporate-managed agent install) instead of storing raw provider API keys in StackStorm pack config.

| Profile | What runs | Operator wiring |
| --- | --- | --- |
| `claude_code` | `agent_cli_binary` (default `claude`) with `-p`, `--output-format=json`, `--bare` | Install [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) on the **same host/user context as the StackStorm action runner** (or a dedicated service account that has completed `claude` login). Set `llm_model` for documentation only; the CLI uses its configured model unless you extend argv via `custom`. |
| `stdin_json_bridge` | `agent_cli_executable` only | Process reads **one JSON line** on stdin (`version`, `user_prompt`, `system_prompt`, `model`, `temperature`) and prints **one JSON object** on stdout with a string field **`content`**. Use this for **Cursor Agent**, **OpenAI Codex CLI**, **OpenCode**, or any tool whose flags change often: put vendor-specific logic in your script and keep the pack config to a single executable path. |
| `custom` | `agent_cli_argv_json` (JSON array of argv strings) | Substitute `{combined_prompt}`, `{user_prompt}`, `{system_prompt}`, `{model}`, `{temperature}` in each argument. Set `agent_cli_stdout_kind` to `raw_text`, `json_content`, or `claude_code_result` to match the program’s stdout. |

**Security:** `agent_cli` runs arbitrary executables with the StackStorm runner’s privileges. Prefer dedicated users, `agent_cli_working_directory`, and read-only images; review argv and bridge scripts in code review.

**Reference:** see [`contrib/agent_cli/README.md`](contrib/agent_cli/README.md) for stdin protocol details and copy-paste bridge sketches.

```bash
st2 run llm_plan_task.llm_chat_complete \
  user_prompt="Reply with one word: OK" \
  system_prompt="You are a terse assistant."
```

**Example result** (`result.result`) — **illustrative**; provider JSON varies.

```json
{
  "raw": {
    "id": "chatcmpl-example",
    "object": "chat.completion",
    "created": 1710000000,
    "model": "gpt-4o-mini",
    "choices": [
      {
        "index": 0,
        "finish_reason": "stop",
        "message": { "role": "assistant", "content": "OK" }
      }
    ]
  },
  "content": "OK"
}
```

### `plan_to_tasks` (Orquesta workflow)

Runs `plan_from_goal` → `tasks_from_plan` and publishes **`bundle`** plus failure fields on errors (see the **`plan_to_tasks` workflow — failure context** section above).

```bash
st2 run llm_plan_task.plan_to_tasks goal="Roll out monitoring"
```

**Example workflow output** (logical shape: published `bundle` matches `tasks_from_plan`; `failure_*` are null on success). `bundle.run_id` is a new UUID each run; shown value is illustrative.

```json
{
  "bundle": {
    "plan": {
      "version": "1",
      "goal": "Roll out monitoring",
      "assumptions": [
        "Template mode: replace this plan with model output by passing structured_plan_json."
      ],
      "risks": [],
      "steps": [
        {
          "id": "clarify",
          "title": "Clarify requirements and success criteria",
          "description": "Confirm scope, constraints, and acceptance checks for: Roll out monitoring",
          "depends_on": []
        },
        {
          "id": "design",
          "title": "Design approach",
          "description": "Outline an implementation or operational approach.",
          "depends_on": ["clarify"]
        },
        {
          "id": "execute",
          "title": "Execute primary work",
          "description": "Carry out the planned steps with traceable outputs.",
          "depends_on": ["design"]
        },
        {
          "id": "verify",
          "title": "Verify and document",
          "description": "Validate results and capture what changed for operators.",
          "depends_on": ["execute"]
        }
      ]
    },
    "tasks": [
      {
        "id": "task-clarify",
        "step_id": "clarify",
        "title": "Clarify requirements and success criteria",
        "description": "Confirm scope, constraints, and acceptance checks for: Roll out monitoring",
        "depends_on": [],
        "status": "pending"
      },
      {
        "id": "task-design",
        "step_id": "design",
        "title": "Design approach",
        "description": "Outline an implementation or operational approach.",
        "depends_on": ["task-clarify"],
        "status": "pending"
      },
      {
        "id": "task-execute",
        "step_id": "execute",
        "title": "Execute primary work",
        "description": "Carry out the planned steps with traceable outputs.",
        "depends_on": ["task-design"],
        "status": "pending"
      },
      {
        "id": "task-verify",
        "step_id": "verify",
        "title": "Verify and document",
        "description": "Validate results and capture what changed for operators.",
        "depends_on": ["task-execute"],
        "status": "pending"
      }
    ],
    "execution_order": [
      "task-clarify",
      "task-design",
      "task-execute",
      "task-verify"
    ],
    "run_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
  },
  "failure_stage": null,
  "failure_message": null,
  "failure_raw": null
}
```

## Tests (without StackStorm)

**pip / venv** (minimal):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-tests.txt
pytest -q
```

**uv** (matches CI):

```bash
uv venv && . .venv/bin/activate
uv pip install -r requirements-tests.txt
uv run pytest -q
```

**Ruff** (lint + format; config in `pyproject.toml`):

```bash
uvx ruff check actions tests
uvx ruff format --check actions tests   # or: uvx ruff format actions tests
```

The suite includes `tests/test_actions_offline.py`, which imports each Python action with a stub `st2actions` base class so action `run()` methods are exercised without the StackStorm runtime.

On GitHub, [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs **EditorConfig** checks, **Keep a Changelog** validation on [`CHANGELOG.md`](CHANGELOG.md), **Conventional Commits** linting on PRs and pushes, **Ruff** (`uvx`), and **pytest** on Python 3.10–3.12 via **uv** (see [Astral uv](https://docs.astral.sh/uv/guides/integration/github/) patterns).

## Contributing

Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (enforced in CI). User-facing changes should be noted under `## [Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) following [Keep a Changelog](https://keepachangelog.com/).

## Full StackStorm smoke (Docker)

When no bare-metal `st2` is available, use the official Docker deployment: [StackStorm Docker install](https://docs.stackstorm.com/install/docker.html) and the [`st2-docker`](https://github.com/StackStorm/st2-docker) compose stack. Start the stack, then:

```bash
docker compose exec st2client bash -lc 'cd /opt/stackstorm/packs.dev && git clone <your-repo-or-copy-pack> llm_plan_task && cd llm_plan_task && st2 pack install file://$PWD'
```

Adjust paths to match how you mount the pack into `st2client` / `packs.dev` (see `ST2_PACKS_DEV` in the compose docs). Then run the same `st2 run llm_plan_task.plan_from_goal` / `plan_to_tasks` commands as above.

## License

MIT — see `LICENSE`.
