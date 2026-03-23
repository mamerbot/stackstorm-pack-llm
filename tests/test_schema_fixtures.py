# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: Apache-2.0

"""Validate golden plan fixtures against JSON Schema and plan_model.validate_plan."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMA_PATH = ROOT / "schemas" / "plan.v1.json"

ACTIONS = ROOT / "actions"
sys.path.insert(0, str(ACTIONS))

from lib.plan_model import PlanValidationError, validate_plan  # noqa: E402


@pytest.fixture(scope="module")
def plan_v1_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def plan_v1_validator(plan_v1_schema: dict) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(plan_v1_schema)


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES.glob("plan_*.json"))


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.name)
def test_fixture_matches_json_schema(path: Path, plan_v1_validator: jsonschema.Draft202012Validator):
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    plan_v1_validator.validate(data)


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.name)
def test_fixture_passes_validate_plan(path: Path):
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    validate_plan(data)


def test_fixture_glob_non_empty():
    assert _fixture_paths(), "expected tests/fixtures/plan_*.json golden files"


def test_schema_rejects_parameters_without_action_ref(plan_v1_validator: jsonschema.Draft202012Validator):
    bad = {
        "goal": "g",
        "steps": [
            {
                "id": "a",
                "title": "A",
                "description": "",
                "depends_on": [],
                "action_parameters": {"k": 1},
            },
        ],
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        plan_v1_validator.validate(bad)


def test_validate_plan_still_rejects_bad_dep_even_if_schema_relaxed():
    """depends_on targets are not expressible in portable JSON Schema; code rejects."""
    # Valid JSON Schema shape but invalid dep id — schema allows strings; validate_plan checks ids.
    loose = {
        "goal": "g",
        "steps": [
            {"id": "a", "title": "A", "description": "", "depends_on": ["missing"]},
        ],
    }
    jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).validate(
        loose
    )
    with pytest.raises(PlanValidationError):
        validate_plan(loose)
