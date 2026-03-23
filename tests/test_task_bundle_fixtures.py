# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

"""Validate golden task bundle fixtures against JSON Schema and validate_task_bundle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
BUNDLE_SCHEMA_PATH = ROOT / "schemas" / "task_bundle.v1.json"

ACTIONS = ROOT / "actions"
sys.path.insert(0, str(ACTIONS))

from lib.plan_model import TaskBundleValidationError, validate_task_bundle  # noqa: E402


@pytest.fixture(scope="module")
def task_bundle_v1_schema() -> dict:
    with BUNDLE_SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def task_bundle_v1_validator(
    task_bundle_v1_schema: dict,
) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(task_bundle_v1_schema)


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES.glob("bundle_*.json"))


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.name)
def test_fixture_matches_json_schema(
    path: Path, task_bundle_v1_validator: jsonschema.Draft202012Validator
):
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    task_bundle_v1_validator.validate(data)


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.name)
def test_fixture_passes_validate_task_bundle(path: Path):
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    validate_task_bundle(data)


def test_fixture_glob_non_empty():
    assert _fixture_paths(), "expected tests/fixtures/bundle_*.json golden files"


def test_validate_task_bundle_rejects_bad_execution_order_json_schema(
    task_bundle_v1_validator: jsonschema.Draft202012Validator,
):
    """execution_order items must be strings (schema); Python checks permutation separately."""

    bad = {
        "plan": {
            "goal": "g",
            "steps": [{"id": "a", "title": "A", "description": "", "depends_on": []}],
        },
        "tasks": [
            {
                "id": "task-a",
                "step_id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "status": "pending",
            }
        ],
        "execution_order": [1],
        "run_id": "00000000-0000-4000-8000-000000000001",
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        task_bundle_v1_validator.validate(bad)


def test_validate_task_bundle_rejects_wrong_topo_even_if_schema_ok(
    task_bundle_v1_validator: jsonschema.Draft202012Validator,
):
    loose = {
        "plan": {
            "goal": "g",
            "steps": [
                {
                    "id": "c",
                    "title": "C",
                    "description": "",
                    "depends_on": ["a"],
                },
                {"id": "a", "title": "A", "description": "", "depends_on": []},
            ],
        },
        "tasks": [
            {
                "id": "task-c",
                "step_id": "c",
                "title": "C",
                "description": "",
                "depends_on": ["task-a"],
                "status": "pending",
            },
            {
                "id": "task-a",
                "step_id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "status": "pending",
            },
        ],
        "execution_order": ["task-c", "task-a"],
        "run_id": "00000000-0000-4000-8000-000000000002",
    }
    task_bundle_v1_validator.validate(loose)
    with pytest.raises(TaskBundleValidationError) as ei:
        validate_task_bundle(loose)
    assert "execution_order" in str(ei.value)
