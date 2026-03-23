# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
