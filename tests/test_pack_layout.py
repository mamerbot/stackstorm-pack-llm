# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "pack.yaml",
    "config.schema.yaml",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "llm_plan_task.yaml.example",
    "actions/plan_from_goal.py",
    "actions/plan_from_goal.yaml",
    "actions/normalize_plan_from_llm.py",
    "actions/normalize_plan_from_llm.yaml",
    "actions/tasks_from_plan.py",
    "actions/tasks_from_plan.yaml",
    "actions/llm_chat_complete.py",
    "actions/llm_chat_complete.yaml",
    "actions/plan_to_tasks.yaml",
    "actions/workflows/plan_to_tasks.yaml",
    "actions/lib/plan_model.py",
    "aliases/plan_to_tasks.yaml",
]


def test_required_pack_files_exist():
    missing = [rel for rel in REQUIRED_FILES if not (ROOT / rel).is_file()]
    assert not missing, "missing files: %s" % ", ".join(missing)


def test_plan_to_tasks_workflow_references_pack_actions():
    wf = (ROOT / "actions/workflows/plan_to_tasks.yaml").read_text(encoding="utf-8")
    assert "llm_plan_task.plan_from_goal" in wf
    assert "llm_plan_task.tasks_from_plan" in wf
    assert "when: <% failed() %>" in wf
    assert "failure_stage" in wf
    assert "failure_message" in wf
    assert "failure_raw" in wf
    assert "core.fail" in wf
    assert "finalize_failure" in wf


def test_orquesta_workflow_yaml_parses():
    for path in (ROOT / "actions/workflows").glob("*.yaml"):
        yaml.safe_load(path.read_text(encoding="utf-8"))
