# Copyright 2026 Emtesseract / Paperclip contributors
# SPDX-License-Identifier: MIT

"""Load pack Python actions without StackStorm installed (fake st2actions only)."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / "actions"


def _install_fake_st2() -> None:
    """Minimal stub so `from st2actions.runners.pythonrunner import Action` succeeds."""
    pythonrunner = types.ModuleType("st2actions.runners.pythonrunner")

    class Action:
        def __init__(self, config=None):
            self.config = config

    pythonrunner.Action = Action

    runners = types.ModuleType("st2actions.runners")
    runners.pythonrunner = pythonrunner

    st2actions = types.ModuleType("st2actions")
    st2actions.runners = runners

    sys.modules["st2actions"] = st2actions
    sys.modules["st2actions.runners"] = runners
    sys.modules["st2actions.runners.pythonrunner"] = pythonrunner


def _load_action_module(name: str):
    _install_fake_st2()
    path = ACTIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"llm_plan_task_pack.{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    # Match StackStorm: actions/ on sys.path so `from lib...` resolves.
    before = sys.path[:]
    sys.path.insert(0, str(ACTIONS))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = before
    return mod


@pytest.fixture(autouse=True)
def _cleanup_sys_modules():
    def _purge():
        for k in list(sys.modules):
            if k.startswith("llm_plan_task_pack."):
                sys.modules.pop(k, None)
        for name in (
            "st2actions",
            "st2actions.runners",
            "st2actions.runners.pythonrunner",
        ):
            sys.modules.pop(name, None)

    _purge()
    yield
    _purge()


def test_plan_from_goal_template_mode():
    mod = _load_action_module("plan_from_goal")
    act = mod.PlanFromGoal()
    ok, plan = act.run(goal="Roll out monitoring")
    assert ok is True
    assert plan["goal"] == "Roll out monitoring"
    assert plan["version"] == "1"
    assert plan["steps"]


def test_plan_from_goal_with_structured_json():
    mod = _load_action_module("plan_from_goal")
    raw = json.dumps(
        {
            "version": "1",
            "goal": "ignored",
            "assumptions": [],
            "risks": [],
            "steps": [{"id": "s1", "title": "Step", "description": "d", "depends_on": []}],
        }
    )
    act = mod.PlanFromGoal()
    ok, plan = act.run(goal="Roll out monitoring", structured_plan_json=raw, override_goal=True)
    assert ok is True
    assert plan["goal"] == "Roll out monitoring"


def test_tasks_from_plan():
    mod_plan = _load_action_module("plan_from_goal")
    mod_tasks = _load_action_module("tasks_from_plan")
    act_p = mod_plan.PlanFromGoal()
    ok, plan = act_p.run(goal="G")
    assert ok
    act_t = mod_tasks.TasksFromPlan()
    ok2, bundle = act_t.run(plan=plan)
    assert ok2 is True
    assert "tasks" in bundle and isinstance(bundle["tasks"], list)
    assert bundle["tasks"][0]["id"]
    assert bundle.get("execution_order") == [t["id"] for t in bundle["tasks"]]


def test_tasks_from_plan_includes_action_ref():
    mod_tasks = _load_action_module("tasks_from_plan")
    act_t = mod_tasks.TasksFromPlan()
    plan = {
        "version": "1",
        "goal": "g",
        "assumptions": [],
        "risks": [],
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_ref": "mypack.do_thing",
            },
        ],
    }
    ok, bundle = act_t.run(plan=plan)
    assert ok is True
    assert bundle["tasks"][0]["action_ref"] == "mypack.do_thing"


def test_tasks_from_plan_includes_action_parameters_with_action_ref():
    mod_tasks = _load_action_module("tasks_from_plan")
    act_t = mod_tasks.TasksFromPlan()
    plan = {
        "version": "1",
        "goal": "g",
        "assumptions": [],
        "risks": [],
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_ref": "mypack.do_thing",
                "action_parameters": {"foo": "bar"},
            },
        ],
    }
    ok, bundle = act_t.run(plan=plan)
    assert ok is True
    assert bundle["tasks"][0]["action_parameters"] == {"foo": "bar"}


def test_tasks_from_plan_rejects_action_parameters_without_action_ref():
    mod_tasks = _load_action_module("tasks_from_plan")
    act_t = mod_tasks.TasksFromPlan()
    plan = {
        "version": "1",
        "goal": "g",
        "assumptions": [],
        "risks": [],
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_parameters": {"only": "params"},
            },
        ],
    }
    ok, err = act_t.run(plan=plan)
    assert ok is False
    assert "action_ref" in err
    assert "JSON Schema" in err


def test_tasks_from_plan_rejects_oversized_plan():
    mod_tasks = _load_action_module("tasks_from_plan")
    act_t = mod_tasks.TasksFromPlan()
    long_title = "x" * 600
    bad = {
        "version": "1",
        "goal": "g",
        "assumptions": [],
        "risks": [],
        "steps": [
            {"id": "a", "title": long_title, "description": "", "depends_on": []},
        ],
    }
    ok, err = act_t.run(plan=bad)
    assert ok is False
    assert "plan.steps[0].title" in err
    assert "max length" in err


def test_tasks_from_plan_rejects_cyclic_depends_on():
    mod_tasks = _load_action_module("tasks_from_plan")
    act_t = mod_tasks.TasksFromPlan()
    cyclic = {
        "version": "1",
        "goal": "g",
        "assumptions": [],
        "risks": [],
        "steps": [
            {"id": "a", "title": "A", "description": "", "depends_on": ["b"]},
            {"id": "b", "title": "B", "description": "", "depends_on": ["a"]},
        ],
    }
    ok, err = act_t.run(plan=cyclic)
    assert ok is False
    assert "cyclic depends_on" in err
    assert "a" in err and "b" in err


def test_normalize_plan_from_llm():
    mod = _load_action_module("normalize_plan_from_llm")
    inner = {
        "version": "1",
        "goal": "g",
        "assumptions": [],
        "risks": [],
        "steps": [
            {"id": "a", "title": "t", "description": "d", "depends_on": []},
        ],
    }
    raw = "```json\n%s\n```" % json.dumps(inner)
    act = mod.NormalizePlanFromLlm()
    ok, plan = act.run(plan_json_str=raw)
    assert ok is True
    assert plan["goal"] == "g"


def test_llm_chat_complete_cursor_requires_explicit_url():
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(config={"llm_provider": "cursor"})
    ok, err = act.run(user_prompt="hi")
    assert ok is False
    assert "llm_chat_completions_url" in err


def test_llm_chat_complete_openai_default_url_without_config_url():
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(config={"api_token": "t"})
    with mock.patch("requests.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }
        ok, body = act.run(user_prompt="hi")
    assert ok is True
    assert body["content"] == "ok"
    args, kwargs = post.call_args
    assert args[0] == "https://api.openai.com/v1/chat/completions"


def test_llm_chat_complete_openai_reads_openai_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(config={"llm_provider": "openai"})
    with mock.patch("requests.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "x"}}],
        }
        ok, _ = act.run(user_prompt="hi")
    assert ok is True
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-from-env"


def test_llm_chat_complete_anthropic_messages_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-env")
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(
        config={
            "llm_provider": "anthropic",
            "llm_model": "claude-3-5-sonnet-20241022",
        }
    )
    with mock.patch("requests.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "content": [{"type": "text", "text": "hello"}],
        }
        ok, body = act.run(user_prompt="u", system_prompt="sys")
    assert ok is True
    assert body["content"] == "hello"
    h = post.call_args.kwargs["headers"]
    assert h["x-api-key"] == "ant-env"
    assert h["anthropic-version"] == "2023-06-01"
    sent = json.loads(post.call_args.kwargs["data"])
    assert sent["model"] == "claude-3-5-sonnet-20241022"
    assert sent["system"] == "sys"
    assert sent["messages"] == [{"role": "user", "content": "u"}]
    assert sent["max_tokens"] == 4096


def test_llm_chat_complete_cursor_bearer_with_custom_url(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "cur-env")
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(
        config={
            "llm_provider": "cursor",
            "llm_chat_completions_url": "https://gateway.example/v1/chat/completions",
        }
    )
    with mock.patch("requests.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "c"}}],
        }
        ok, body = act.run(user_prompt="p")
    assert ok is True
    assert body["content"] == "c"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer cur-env"


def test_llm_chat_complete_invalid_provider():
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(config={"llm_provider": "azure"})
    ok, err = act.run(user_prompt="hi")
    assert ok is False
    assert "llm_provider" in err


def test_llm_chat_complete_invalid_access_mode():
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(config={"llm_access_mode": "grpc"})
    ok, err = act.run(user_prompt="hi")
    assert ok is False
    assert "llm_access_mode" in err


def test_llm_chat_complete_agent_cli_requires_profile():
    mod = _load_action_module("llm_chat_complete")
    act = mod.LlmChatComplete(config={"llm_access_mode": "agent_cli"})
    ok, err = act.run(user_prompt="hi")
    assert ok is False
    assert "agent_cli_profile" in err


def test_llm_chat_complete_agent_cli_stdin_json_bridge():
    mod = _load_action_module("llm_chat_complete")
    ac = sys.modules["lib.agent_cli"]
    act = mod.LlmChatComplete(
        config={
            "llm_access_mode": "agent_cli",
            "agent_cli_profile": "stdin_json_bridge",
            "agent_cli_executable": "/opt/stackstorm/scripts/bridge.sh",
        }
    )
    with mock.patch.object(ac.subprocess, "run") as run:
        run.return_value = CompletedProcess(
            ["/opt/stackstorm/scripts/bridge.sh"],
            0,
            stdout=b'{"content":"from-bridge"}',
            stderr=b"",
        )
        ok, body = act.run(user_prompt="hi", system_prompt="sys")
    assert ok is True
    assert body["content"] == "from-bridge"
    assert body["raw"]["content"] == "from-bridge"
    call_kw = run.call_args.kwargs
    assert call_kw["input"].decode("utf-8").startswith('{"version": "1"')
    assert '"user_prompt": "hi"' in call_kw["input"].decode("utf-8")


def test_llm_chat_complete_agent_cli_claude_code_json():
    mod = _load_action_module("llm_chat_complete")
    ac = sys.modules["lib.agent_cli"]
    act = mod.LlmChatComplete(
        config={
            "llm_access_mode": "agent_cli",
            "agent_cli_profile": "claude_code",
            "agent_cli_binary": "claude",
        }
    )
    payload = json.dumps({"type": "result", "subtype": "success", "result": "hello-claude"}).encode(
        "utf-8"
    )
    with mock.patch.object(ac.subprocess, "run") as run:
        run.return_value = CompletedProcess(
            ["claude", "-p", "u", "--output-format", "json", "--bare"],
            0,
            stdout=payload,
            stderr=b"",
        )
        ok, body = act.run(user_prompt="u")
    assert ok is True
    assert body["content"] == "hello-claude"
    argv = run.call_args[0][0]
    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert argv[2] == "u"


def test_llm_chat_complete_agent_cli_custom_raw_stdout():
    mod = _load_action_module("llm_chat_complete")
    ac = sys.modules["lib.agent_cli"]
    act = mod.LlmChatComplete(
        config={
            "llm_access_mode": "agent_cli",
            "agent_cli_profile": "custom",
            "agent_cli_stdout_kind": "raw_text",
            "agent_cli_argv_json": '["/bin/echo", "{user_prompt}"]',
        }
    )
    with mock.patch.object(ac.subprocess, "run") as run:
        run.return_value = CompletedProcess(
            ["/bin/echo", "ping"],
            0,
            stdout=b"ping\n",
            stderr=b"",
        )
        ok, body = act.run(user_prompt="ping")
    assert ok is True
    assert body["content"] == "ping"


def test_llm_chat_complete_happy_path():
    mod = _load_action_module("llm_chat_complete")
    payload = {
        "choices": [{"message": {"content": "  hello  "}}],
    }
    act = mod.LlmChatComplete(
        config={
            "llm_chat_completions_url": "https://example.invalid/v1/chat/completions",
            "api_token": "t",
        }
    )
    with mock.patch("requests.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = payload
        ok, body = act.run(user_prompt="x")
    assert ok is True
    assert body["content"] == "hello"
    post.assert_called_once()
