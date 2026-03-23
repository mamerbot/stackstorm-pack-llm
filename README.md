# StackStorm pack: `llm_plan_task`

Actions and an Orquesta workflow for **LLM-assisted planning** and **task decomposition** inside StackStorm.

**Source repository:** [github.com/mamerbot/stackstorm-pack-llm](https://github.com/mamerbot/stackstorm-pack-llm)

## Layout

- `pack.yaml` — pack metadata
- `config.schema.yaml` — optional HTTP settings for `llm_chat_complete`
- `actions/` — python-script actions + `workflows/plan_to_tasks.yaml`
- `tests/` — off-box unit tests for the pure plan helpers

## Actions

| Action | Purpose |
| --- | --- |
| `plan_from_goal` | Build a normalized plan from a goal; optionally merge validated JSON from an LLM. |
| `normalize_plan_from_llm` | Parse/validate raw LLM output (including ```json fences) into a plan object. |
| `tasks_from_plan` | Expand a validated plan into pending tasks with stable ids and dependency edges. |
| `llm_chat_complete` | Optional OpenAI-compatible `chat/completions` POST using pack config. |
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

## Try it

```bash
st2 run llm_plan_task.plan_from_goal goal="Roll out monitoring"
st2 run llm_plan_task.plan_to_tasks goal="Roll out monitoring"
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

On GitHub, [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs **Ruff** (`uvx`) and **pytest** on Python 3.10–3.12 via **uv** (see [Astral uv](https://docs.astral.sh/uv/guides/integration/github/) patterns).

## Full StackStorm smoke (Docker)

When no bare-metal `st2` is available, use the official Docker deployment: [StackStorm Docker install](https://docs.stackstorm.com/install/docker.html) and the [`st2-docker`](https://github.com/StackStorm/st2-docker) compose stack. Start the stack, then:

```bash
docker compose exec st2client bash -lc 'cd /opt/stackstorm/packs.dev && git clone <your-repo-or-copy-pack> llm_plan_task && cd llm_plan_task && st2 pack install file://$PWD'
```

Adjust paths to match how you mount the pack into `st2client` / `packs.dev` (see `ST2_PACKS_DEV` in the compose docs). Then run the same `st2 run llm_plan_task.plan_from_goal` / `plan_to_tasks` commands as above.

## License

Apache-2.0 — see `LICENSE`.
