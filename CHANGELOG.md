# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CI: **stackstorm-pack** job runs Orquesta workflow `llm_plan_task.plan_to_tasks` with goal
  `ci-offline-plan-to-tasks` and `structured_plan_json` from `tests/fixtures/plan_minimal.json`
  (host `PLAN_JSON` + `st2 run ... --wait`) so workflow registration and cross-step data passing are
  exercised in st2-docker alongside standalone actions.
- CI: after `validate_plan`, the **stackstorm-pack** job runs `llm_plan_task.validate_task_bundle`
  with `tests/fixtures/bundle_minimal.json` inside st2-docker (same host `BUNDLE_JSON` env pattern as
  `PLAN_JSON` for plan validation).
- Offline pytest module `tests/test_opencode_bridge_offline.py` exercising
  `contrib/agent_cli/example_opencode_bridge.py` with a temporary fake OpenCode binary (JSONL
  `type: text`), including empty/whitespace `model` fallback via `LLM_PLAN_TASK_OPENCODE_MODEL`.
- Standalone StackStorm actions `validate_plan` and `validate_task_bundle` for validating
  parsed plan and bundle objects at workflow boundaries (same logic as `normalize_plan_from_llm` /
  `tasks_from_plan` success paths).
- `llm_access_mode` `agent_cli` for `llm_chat_complete`: coding-agent / ACP-style access via
  `agent_cli_profile` `stdin_json_bridge` | `claude_code` | `custom`, optional `contrib/agent_cli`
  bridge notes, and subprocess-based execution (no HTTP API key in the pack for that path).
- `llm_chat_complete` multi-provider support: `llm_provider` `openai` | `anthropic` | `cursor`,
  credential fallbacks `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CURSOR_API_KEY`, Anthropic Messages
  API wiring, optional `cursor_api_basic_auth` and `llm_max_tokens`.
- CI checks for EditorConfig, Keep a Changelog formatting, and Conventional Commits.

## [0.1.0] - 2026-03-23

### Added

- StackStorm pack `llm_plan_task`: LLM-assisted planning actions, Orquesta workflows, and offline tests.
