# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

import pytest

ACTIONS = Path(__file__).resolve().parents[1] / "actions"
sys.path.insert(0, str(ACTIONS))

from lib.plan_model import (  # noqa: E402
    MAX_ACTION_PARAMETERS_UTF8_BYTES,
    MAX_PLAN_STEPS,
    MAX_STEP_ACTION_REF_CHARS,
    PlanValidationError,
    merge_plan_with_goal,
    parse_plan_json,
    plan_to_tasks,
    template_plan_from_goal,
    validate_plan,
    validate_task_bundle,
)


def test_template_plan_from_goal_shapes():
    plan = template_plan_from_goal("Ship the StackStorm pack")
    validate_plan(plan)
    bundle = plan_to_tasks(plan)
    validate_task_bundle(bundle)
    assert len(bundle["tasks"]) == len(plan["steps"])
    assert bundle["tasks"][0]["status"] == "pending"
    assert bundle["execution_order"] == [t["id"] for t in bundle["tasks"]]


def test_parse_plan_json_strips_fence():
    inner = {
        "goal": "x",
        "steps": [{"id": "a", "title": "A", "description": "", "depends_on": []}],
    }
    wrapped = "```json\n%s\n```" % json.dumps(inner)
    assert validate_plan(parse_plan_json(wrapped))["goal"] == "x"


def test_validate_plan_schema_rejects_null_step_description():
    """JSON null for step.description violates plan.v1.json; Python alone would coerce to ''."""

    bad = {
        "goal": "g",
        "steps": [
            {"id": "a", "title": "A", "description": None, "depends_on": []},
        ],
    }
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(bad)
    msg = str(ei.value)
    assert "JSON Schema" in msg
    assert "$.steps[0].description" in msg


def test_validate_plan_rejects_too_many_steps():
    steps = [
        {"id": "s%d" % i, "title": "T", "description": "", "depends_on": []}
        for i in range(MAX_PLAN_STEPS + 1)
    ]
    huge = {"goal": "g", "assumptions": [], "risks": [], "steps": steps}
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(huge)
    assert "plan.steps count exceeds limit" in str(ei.value)
    assert str(MAX_PLAN_STEPS) in str(ei.value)


def test_validate_plan_rejects_bad_dep():
    bad = {
        "goal": "g",
        "steps": [
            {"id": "a", "title": "A", "description": "", "depends_on": ["missing"]},
        ],
    }
    with pytest.raises(PlanValidationError):
        validate_plan(bad)


def test_merge_plan_with_goal_overrides():
    plan = validate_plan(
        {
            "goal": "old",
            "steps": [
                {"id": "a", "title": "A", "description": "", "depends_on": []},
            ],
        }
    )
    merged = merge_plan_with_goal(plan, "new goal")
    assert merged["goal"] == "new goal"
    assert merged["steps"] == plan["steps"]


def test_validate_plan_action_ref_valid_and_plan_to_tasks():
    plan = validate_plan(
        {
            "goal": "g",
            "steps": [
                {
                    "id": "a",
                    "title": "A",
                    "description": "",
                    "depends_on": [],
                    "action_ref": "core.local",
                },
                {"id": "b", "title": "B", "description": "", "depends_on": ["a"]},
            ],
        }
    )
    assert "action_ref" in plan["steps"][0]
    assert plan["steps"][0]["action_ref"] == "core.local"
    assert "action_ref" not in plan["steps"][1]
    bundle = plan_to_tasks(plan)
    assert bundle["tasks"][0]["action_ref"] == "core.local"
    assert "action_ref" not in bundle["tasks"][1]


def test_validate_plan_action_ref_whitespace_treated_absent():
    plan = validate_plan(
        {
            "goal": "g",
            "steps": [
                {
                    "id": "a",
                    "title": "A",
                    "description": "",
                    "depends_on": [],
                    "action_ref": "  ",
                },
            ],
        }
    )
    assert "action_ref" not in plan["steps"][0]


def test_validate_plan_action_ref_invalid_pattern():
    bad = {
        "goal": "g",
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_ref": "no_dot",
            },
        ],
    }
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(bad)
    assert "action_ref" in str(ei.value)


def test_validate_plan_action_ref_oversized():
    long_ref = "a." + ("x" * MAX_STEP_ACTION_REF_CHARS)
    bad = {
        "goal": "g",
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_ref": long_ref,
            },
        ],
    }
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(bad)
    assert "action_ref" in str(ei.value)
    assert "max length" in str(ei.value)


def test_validate_plan_action_parameters_requires_action_ref():
    bad = {
        "goal": "g",
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_parameters": {"cmd": "echo hi"},
            },
        ],
    }
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(bad)
    msg = str(ei.value)
    assert "action_ref" in msg
    assert "JSON Schema" in msg


def test_validate_plan_action_parameters_must_be_object():
    bad = {
        "goal": "g",
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_ref": "core.local",
                "action_parameters": [1, 2],
            },
        ],
    }
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(bad)
    assert "action_parameters" in str(ei.value)
    assert "object" in str(ei.value)


def test_validate_plan_action_ref_with_parameters_and_plan_to_tasks():
    plan = validate_plan(
        {
            "goal": "g",
            "steps": [
                {
                    "id": "a",
                    "title": "A",
                    "description": "",
                    "depends_on": [],
                    "action_ref": "core.local",
                    "action_parameters": {"cmd": "echo ok", "nested": {"x": 1}},
                },
                {"id": "b", "title": "B", "description": "", "depends_on": ["a"]},
            ],
        }
    )
    assert plan["steps"][0]["action_parameters"] == {
        "cmd": "echo ok",
        "nested": {"x": 1},
    }
    assert "action_parameters" not in plan["steps"][1]
    bundle = plan_to_tasks(plan)
    assert bundle["tasks"][0]["action_parameters"] == {
        "cmd": "echo ok",
        "nested": {"x": 1},
    }
    assert "action_parameters" not in bundle["tasks"][1]


def test_validate_plan_action_parameters_oversized_serialized():
    # Single key: JSON body is longer than the raw string (quotes + key).
    filler = "x" * MAX_ACTION_PARAMETERS_UTF8_BYTES
    bad = {
        "goal": "g",
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_ref": "core.local",
                "action_parameters": {"k": filler},
            },
        ],
    }
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(bad)
    assert "action_parameters" in str(ei.value)
    assert "UTF-8 bytes" in str(ei.value)


def test_validate_plan_action_parameters_too_deep():
    inner: dict = {"leaf": 1}
    cur = inner
    for _ in range(30):
        cur = {"d": cur}
    bad = {
        "goal": "g",
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_ref": "core.local",
                "action_parameters": cur,
            },
        ],
    }
    with pytest.raises(PlanValidationError) as ei:
        validate_plan(bad)
    assert "nesting depth" in str(ei.value)


def test_plan_to_tasks_execution_order_respects_deps_not_step_list_order():
    plan = validate_plan(
        {
            "goal": "g",
            "steps": [
                {"id": "c", "title": "C", "description": "", "depends_on": ["a"]},
                {"id": "a", "title": "A", "description": "", "depends_on": []},
            ],
        }
    )
    bundle = plan_to_tasks(plan)
    assert [t["id"] for t in bundle["tasks"]] == ["task-c", "task-a"]
    assert bundle["execution_order"] == ["task-a", "task-c"]


def test_plan_to_tasks_execution_order_parallel_tie_break_by_plan_step_order():
    plan = validate_plan(
        {
            "goal": "g",
            "steps": [
                {"id": "b", "title": "B", "description": "", "depends_on": []},
                {"id": "a", "title": "A", "description": "", "depends_on": []},
            ],
        }
    )
    bundle = plan_to_tasks(plan)
    assert bundle["execution_order"] == ["task-b", "task-a"]


def test_plan_to_tasks_execution_order_diamond():
    plan = validate_plan(
        {
            "goal": "g",
            "steps": [
                {"id": "root", "title": "R", "description": "", "depends_on": []},
                {"id": "left", "title": "L", "description": "", "depends_on": ["root"]},
                {
                    "id": "right",
                    "title": "R2",
                    "description": "",
                    "depends_on": ["root"],
                },
                {
                    "id": "join",
                    "title": "J",
                    "description": "",
                    "depends_on": ["left", "right"],
                },
            ],
        }
    )
    bundle = plan_to_tasks(plan)
    assert bundle["execution_order"] == [
        "task-root",
        "task-left",
        "task-right",
        "task-join",
    ]
