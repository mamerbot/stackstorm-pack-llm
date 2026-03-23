# Copyright 2026 Emtesseract / Paperclip contributors
# SPDX-License-Identifier: MIT
"""Shared plan/task helpers (pure Python; safe to unit test off-box)."""

from __future__ import annotations

import json
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import jsonschema


class PlanValidationError(ValueError):
    pass


class TaskBundleValidationError(ValueError):
    pass


_PLAN_V1_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "plan.v1.json"
_TASK_BUNDLE_V1_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "schemas" / "task_bundle.v1.json"
)


@lru_cache(maxsize=1)
def _plan_v1_draft202012_validator() -> jsonschema.Draft202012Validator:
    with _PLAN_V1_SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    return jsonschema.Draft202012Validator(schema)


@lru_cache(maxsize=1)
def _task_bundle_v1_draft202012_validator() -> jsonschema.Draft202012Validator:
    with _TASK_BUNDLE_V1_SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    return jsonschema.Draft202012Validator(schema)


def _schema_validation_error_message(exc: jsonschema.ValidationError, label: str = "plan") -> str:
    loc = exc.json_path if exc.json_path else "$"
    return "%s JSON Schema validation failed at %s: %s" % (label, loc, exc.message)


def _validate_plan_against_v1_schema(plan: dict[str, Any]) -> None:
    """Structural check against ``schemas/plan.v1.json`` (Draft 2020-12)."""

    try:
        _plan_v1_draft202012_validator().validate(plan)
    except jsonschema.ValidationError as exc:
        raise PlanValidationError(_schema_validation_error_message(exc, "plan")) from exc


def _validate_task_bundle_against_v1_schema(bundle: dict[str, Any]) -> None:
    """Structural check against ``schemas/task_bundle.v1.json`` (Draft 2020-12)."""

    try:
        _task_bundle_v1_draft202012_validator().validate(bundle)
    except jsonschema.ValidationError as exc:
        raise TaskBundleValidationError(
            _schema_validation_error_message(exc, "task bundle")
        ) from exc


def _assert_task_bundle_invariants(bundle: dict[str, Any], plan: dict[str, Any]) -> None:
    """Python-only checks: task rows mirror plan steps; execution_order matches code."""

    tasks: list[dict[str, Any]] = bundle["tasks"]
    steps = plan["steps"]
    if len(tasks) != len(steps):
        raise TaskBundleValidationError(
            "bundle.tasks length (%d) must match plan.steps length (%d)" % (len(tasks), len(steps))
        )
    task_ids = [t["id"] for t in tasks]
    id_set = set(task_ids)
    if len(id_set) != len(task_ids):
        raise TaskBundleValidationError("bundle.tasks contains duplicate task ids")
    for i, (t, s) in enumerate(zip(tasks, steps, strict=True)):
        exp_id = "task-%s" % s["id"]
        if t["id"] != exp_id:
            raise TaskBundleValidationError(
                "bundle.tasks[%d].id must be %r (got %r)" % (i, exp_id, t["id"])
            )
        if t["step_id"] != s["id"]:
            raise TaskBundleValidationError(
                "bundle.tasks[%d].step_id must match plan.steps[%d].id (%r vs %r)"
                % (i, i, t["step_id"], s["id"])
            )
        if t["title"] != s["title"]:
            raise TaskBundleValidationError("bundle.tasks[%d].title must match plan step title" % i)
        if t["description"] != s["description"]:
            raise TaskBundleValidationError(
                "bundle.tasks[%d].description must match plan step description" % i
            )
        exp_deps = ["task-%s" % d for d in s["depends_on"]]
        if t["depends_on"] != exp_deps:
            raise TaskBundleValidationError(
                "bundle.tasks[%d].depends_on must be %r (got %r)" % (i, exp_deps, t["depends_on"])
            )
        if t["status"] != "pending":
            raise TaskBundleValidationError(
                "bundle.tasks[%d].status must be 'pending' (got %r)" % (i, t["status"])
            )
        ar_step = s.get("action_ref")
        ar_task = t.get("action_ref")
        if ar_step is None:
            if ar_task is not None:
                raise TaskBundleValidationError(
                    "bundle.tasks[%d].action_ref must be absent when plan step has none" % i
                )
        else:
            if ar_task != ar_step:
                raise TaskBundleValidationError(
                    "bundle.tasks[%d].action_ref must match plan step (%r vs %r)"
                    % (i, ar_task, ar_step)
                )
        ap_step = s.get("action_parameters")
        ap_task = t.get("action_parameters")
        if ap_step is None:
            if ap_task is not None:
                raise TaskBundleValidationError(
                    "bundle.tasks[%d].action_parameters must be absent when plan step has none" % i
                )
        else:
            if ap_task != ap_step:
                raise TaskBundleValidationError(
                    "bundle.tasks[%d].action_parameters must match plan step object" % i
                )

    order = bundle["execution_order"]
    if set(order) != id_set:
        raise TaskBundleValidationError(
            "bundle.execution_order must list each task id exactly once"
        )
    if len(order) != len(task_ids):
        raise TaskBundleValidationError(
            "bundle.execution_order length must match bundle.tasks length"
        )
    expected_order = _execution_order_for_tasks(tasks)
    if order != expected_order:
        raise TaskBundleValidationError(
            "bundle.execution_order must match topological order %r (got %r)"
            % (expected_order, order)
        )

    rid = bundle["run_id"]
    if not isinstance(rid, str) or not rid.strip():
        raise TaskBundleValidationError("bundle.run_id must be a non-empty string")
    try:
        UUID(rid)
    except ValueError as exc:
        raise TaskBundleValidationError("bundle.run_id must be a UUID string: %s" % exc) from exc


def validate_task_bundle(bundle: Any) -> dict[str, Any]:
    """Validate a task bundle: JSON Schema (v1), embedded plan (plan v1), and invariants."""

    if not isinstance(bundle, dict):
        raise TaskBundleValidationError("task bundle must be a JSON object")
    _validate_task_bundle_against_v1_schema(bundle)
    raw_plan = bundle.get("plan")
    if not isinstance(raw_plan, dict):
        raise TaskBundleValidationError("bundle.plan must be a JSON object")
    plan = validate_plan(raw_plan)
    bundle = dict(bundle)
    bundle["plan"] = plan
    _assert_task_bundle_invariants(bundle, plan)
    return bundle


# Upper bounds for plan size (fail fast before heavy normalization / task expansion).
MAX_PLAN_STEPS = 128
MAX_PLAN_GOAL_CHARS = 4096
MAX_PLAN_VERSION_CHARS = 64
MAX_PLAN_ASSUMPTION_ENTRIES = 64
MAX_PLAN_RISK_ENTRIES = 64
MAX_PLAN_ASSUMPTION_RISK_ITEM_CHARS = 2048

MAX_STEP_ID_CHARS = 128
MAX_STEP_TITLE_CHARS = 512
MAX_STEP_DESCRIPTION_CHARS = 16384
MAX_STEP_DEPENDS_ON_ENTRIES = 64
MAX_STEP_ACTION_REF_CHARS = 256

# Per-step StackStorm action parameters (JSON object only).
# Validated before merge into normalized plans.
MAX_ACTION_PARAMETERS_UTF8_BYTES = 8192
MAX_ACTION_PARAMETERS_NESTING_DEPTH = 16
MAX_ACTION_PARAMETERS_KEYS_PER_OBJECT = 64
MAX_ACTION_PARAMETERS_ARRAY_LENGTH = 64

# StackStorm-style action reference: exactly one dot separating non-empty
# "pack" and "action" tokens (letters, digits, underscore only).
_ACTION_REF_RE = re.compile(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$")


def _raise_if_too_long(field_label: str, value: str, limit: int) -> None:
    n = len(value)
    if n > limit:
        raise PlanValidationError(
            "%s exceeds max length (%d characters, limit %d)" % (field_label, n, limit)
        )


def _validate_action_parameters(obj: dict[str, Any], step_index: int) -> dict[str, Any]:
    """Validate shape/size of action_parameters; return a JSON-roundtripped copy."""

    def walk(node: Any, depth: int) -> None:
        if isinstance(node, dict):
            if depth > MAX_ACTION_PARAMETERS_NESTING_DEPTH:
                raise PlanValidationError(
                    "plan.steps[%d].action_parameters exceeds max nesting depth (limit %d)"
                    % (step_index, MAX_ACTION_PARAMETERS_NESTING_DEPTH)
                )
            if len(node) > MAX_ACTION_PARAMETERS_KEYS_PER_OBJECT:
                raise PlanValidationError(
                    "plan.steps[%d].action_parameters object has too many keys "
                    "(got %d, limit %d)"
                    % (step_index, len(node), MAX_ACTION_PARAMETERS_KEYS_PER_OBJECT)
                )
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            if depth > MAX_ACTION_PARAMETERS_NESTING_DEPTH:
                raise PlanValidationError(
                    "plan.steps[%d].action_parameters exceeds max nesting depth (limit %d)"
                    % (step_index, MAX_ACTION_PARAMETERS_NESTING_DEPTH)
                )
            if len(node) > MAX_ACTION_PARAMETERS_ARRAY_LENGTH:
                raise PlanValidationError(
                    "plan.steps[%d].action_parameters array is too long "
                    "(got %d, limit %d)"
                    % (step_index, len(node), MAX_ACTION_PARAMETERS_ARRAY_LENGTH)
                )
            for v in node:
                walk(v, depth + 1)
        elif node is None or isinstance(node, (bool, int, float, str)):
            return
        else:
            raise PlanValidationError(
                "plan.steps[%d].action_parameters contains unsupported JSON value type %s"
                % (step_index, type(node).__name__)
            )

    try:
        blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PlanValidationError(
            "plan.steps[%d].action_parameters is not JSON-serializable: %s" % (step_index, exc)
        ) from exc
    n_bytes = len(blob.encode("utf-8"))
    if n_bytes > MAX_ACTION_PARAMETERS_UTF8_BYTES:
        raise PlanValidationError(
            "plan.steps[%d].action_parameters serialized size exceeds limit "
            "(%d UTF-8 bytes, limit %d)" % (step_index, n_bytes, MAX_ACTION_PARAMETERS_UTF8_BYTES)
        )
    walk(obj, 0)
    return json.loads(blob)


def _dependency_cycle_step_ids(steps: list[dict[str, Any]]) -> list[str] | None:
    """Return step ids on a directed cycle in the depends_on graph, or None.

    Traversal follows edges step -> prerequisite (each entry in depends_on).
    """
    by_id = {s["id"]: s for s in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(u: str, path: list[str]) -> list[str] | None:
        if u in visiting:
            i = path.index(u)
            return path[i:]
        if u in visited:
            return None
        visiting.add(u)
        path.append(u)
        for v in by_id[u]["depends_on"]:
            c = dfs(v, path)
            if c is not None:
                return c
        path.pop()
        visiting.remove(u)
        visited.add(u)
        return None

    for sid in by_id:
        if sid not in visited:
            c = dfs(sid, [])
            if c is not None:
                return c
    return None


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def parse_plan_json(plan_json_str: str) -> Any:
    raw = _strip_code_fence(plan_json_str)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanValidationError("plan_json_str is not valid JSON: %s" % exc) from exc


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PlanValidationError("plan must be a JSON object")
    _validate_plan_against_v1_schema(plan)
    goal = plan.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise PlanValidationError("plan.goal must be a non-empty string")
    _raise_if_too_long("plan.goal", goal.strip(), MAX_PLAN_GOAL_CHARS)
    ver_raw = str(plan.get("version") or "1")
    _raise_if_too_long("plan.version", ver_raw, MAX_PLAN_VERSION_CHARS)
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise PlanValidationError("plan.steps must be a non-empty list")
    if len(steps) > MAX_PLAN_STEPS:
        raise PlanValidationError(
            "plan.steps count exceeds limit (got %d, limit %d)" % (len(steps), MAX_PLAN_STEPS)
        )
    seen: set[str] = set()
    norm_steps: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlanValidationError("plan.steps[%d] must be an object" % i)
        sid = step.get("id")
        if not isinstance(sid, str) or not sid.strip():
            sid = "step-%d" % (i + 1)
        else:
            _raise_if_too_long("plan.steps[%d].id" % i, sid.strip(), MAX_STEP_ID_CHARS)
        title = step.get("title")
        if not isinstance(title, str) or not title.strip():
            raise PlanValidationError("plan.steps[%d].title must be a non-empty string" % i)
        _raise_if_too_long("plan.steps[%d].title" % i, title.strip(), MAX_STEP_TITLE_CHARS)
        desc = step.get("description")
        if desc is not None and not isinstance(desc, str):
            raise PlanValidationError("plan.steps[%d].description must be a string if set" % i)
        if isinstance(desc, str) and desc.strip():
            _raise_if_too_long(
                "plan.steps[%d].description" % i,
                desc.strip(),
                MAX_STEP_DESCRIPTION_CHARS,
            )
        deps = step.get("depends_on", [])
        if deps is None:
            deps = []
        if not isinstance(deps, list) or not all(isinstance(x, str) for x in deps):
            raise PlanValidationError("plan.steps[%d].depends_on must be a list of strings" % i)
        if len(deps) > MAX_STEP_DEPENDS_ON_ENTRIES:
            raise PlanValidationError(
                "plan.steps[%d].depends_on count exceeds limit (got %d, limit %d)"
                % (i, len(deps), MAX_STEP_DEPENDS_ON_ENTRIES)
            )
        for j, dep in enumerate(deps):
            if isinstance(dep, str) and dep.strip():
                _raise_if_too_long(
                    "plan.steps[%d].depends_on[%d]" % (i, j),
                    dep.strip(),
                    MAX_STEP_ID_CHARS,
                )
        action_ref_raw = step.get("action_ref")
        action_ref_norm: str | None = None
        if action_ref_raw is not None:
            if not isinstance(action_ref_raw, str):
                raise PlanValidationError("plan.steps[%d].action_ref must be a string if set" % i)
            ar = action_ref_raw.strip()
            if ar:
                _raise_if_too_long("plan.steps[%d].action_ref" % i, ar, MAX_STEP_ACTION_REF_CHARS)
                if not _ACTION_REF_RE.match(ar):
                    raise PlanValidationError(
                        "plan.steps[%d].action_ref must look like pack.action "
                        "(non-empty pack and action tokens; letters, digits, underscore only)" % i
                    )
                action_ref_norm = ar
        ap_raw = step.get("action_parameters")
        ap_norm: dict[str, Any] | None = None
        if ap_raw is not None:
            if not isinstance(ap_raw, dict):
                raise PlanValidationError(
                    "plan.steps[%d].action_parameters must be a JSON object if set" % i
                )
            if action_ref_norm is None:
                raise PlanValidationError(
                    "plan.steps[%d].action_parameters requires a non-empty action_ref" % i
                )
            ap_norm = _validate_action_parameters(ap_raw, i)
        if sid in seen:
            raise PlanValidationError("duplicate step id %r" % sid)
        seen.add(sid)
        step_out: dict[str, Any] = {
            "id": sid.strip(),
            "title": title.strip(),
            "description": (desc or "").strip(),
            "depends_on": [d.strip() for d in deps if isinstance(d, str) and d.strip()],
        }
        if action_ref_norm is not None:
            step_out["action_ref"] = action_ref_norm
        if ap_norm is not None:
            step_out["action_parameters"] = ap_norm
        norm_steps.append(step_out)
    for i, step in enumerate(norm_steps):
        for dep in step["depends_on"]:
            if dep not in seen:
                raise PlanValidationError(
                    "plan.steps[%d] depends_on %r which is not a step id" % (i, dep)
                )
    cycle = _dependency_cycle_step_ids(norm_steps)
    if cycle is not None:
        loop = " -> ".join(cycle + [cycle[0]])
        raise PlanValidationError(
            "plan has a cyclic depends_on chain (cannot order steps): %s" % loop
        )
    assumptions = plan.get("assumptions", [])
    if assumptions is None:
        assumptions = []
    if not isinstance(assumptions, list) or not all(isinstance(x, str) for x in assumptions):
        raise PlanValidationError("plan.assumptions must be a list of strings")
    if len(assumptions) > MAX_PLAN_ASSUMPTION_ENTRIES:
        raise PlanValidationError(
            "plan.assumptions count exceeds limit (got %d, limit %d)"
            % (len(assumptions), MAX_PLAN_ASSUMPTION_ENTRIES)
        )
    for j, a in enumerate(assumptions):
        if isinstance(a, str) and a.strip():
            _raise_if_too_long(
                "plan.assumptions[%d]" % j,
                a.strip(),
                MAX_PLAN_ASSUMPTION_RISK_ITEM_CHARS,
            )
    risks = plan.get("risks", [])
    if risks is None:
        risks = []
    if not isinstance(risks, list) or not all(isinstance(x, str) for x in risks):
        raise PlanValidationError("plan.risks must be a list of strings")
    if len(risks) > MAX_PLAN_RISK_ENTRIES:
        raise PlanValidationError(
            "plan.risks count exceeds limit (got %d, limit %d)"
            % (len(risks), MAX_PLAN_RISK_ENTRIES)
        )
    for j, r in enumerate(risks):
        if isinstance(r, str) and r.strip():
            _raise_if_too_long("plan.risks[%d]" % j, r.strip(), MAX_PLAN_ASSUMPTION_RISK_ITEM_CHARS)
    return {
        "version": ver_raw,
        "goal": goal.strip(),
        "steps": norm_steps,
        "assumptions": [a.strip() for a in assumptions if a.strip()],
        "risks": [r.strip() for r in risks if r.strip()],
    }


def template_plan_from_goal(goal: str) -> dict[str, Any]:
    g = goal.strip()
    return {
        "version": "1",
        "goal": g,
        "assumptions": [
            "Template mode: replace this plan with model output by passing structured_plan_json.",
        ],
        "risks": [],
        "steps": [
            {
                "id": "clarify",
                "title": "Clarify requirements and success criteria",
                "description": "Confirm scope, constraints, and acceptance checks for: %s" % g,
                "depends_on": [],
            },
            {
                "id": "design",
                "title": "Design approach",
                "description": "Outline an implementation or operational approach.",
                "depends_on": ["clarify"],
            },
            {
                "id": "execute",
                "title": "Execute primary work",
                "description": "Carry out the planned steps with traceable outputs.",
                "depends_on": ["design"],
            },
            {
                "id": "verify",
                "title": "Verify and document",
                "description": "Validate results and capture what changed for operators.",
                "depends_on": ["execute"],
            },
        ],
    }


def _execution_order_for_tasks(tasks: list[dict[str, Any]]) -> list[str]:
    """Kahn topological order over task ids using each task's depends_on edges.

    ``validate_plan`` ensures the step graph is acyclic; task edges mirror step deps.
    When multiple tasks are ready, order by plan step list index (position in *tasks*),
    then by task id for a fully deterministic tie-break.
    """
    task_ids: list[str] = [t["id"] for t in tasks]
    id_set: set[str] = set(task_ids)
    step_index = {t["id"]: i for i, t in enumerate(tasks)}
    successors: dict[str, list[str]] = {tid: [] for tid in task_ids}
    indegree: dict[str, int] = {}
    for t in tasks:
        tid = t["id"]
        deps = t.get("depends_on", [])
        indegree[tid] = len(deps)
        for dep in deps:
            if dep in id_set:
                successors[dep].append(tid)
    order: list[str] = []
    placed: set[str] = set()
    while len(placed) < len(task_ids):
        ready = [tid for tid in task_ids if indegree[tid] == 0 and tid not in placed]
        if not ready:
            # Defensive: DAG invariant comes from validate_plan / plan_to_tasks construction.
            raise RuntimeError("task dependency graph has a cycle or inconsistent ids")
        ready.sort(key=lambda tid: (step_index[tid], tid))
        u = ready[0]
        placed.add(u)
        order.append(u)
        for v in successors[u]:
            indegree[v] -= 1
    return order


def plan_to_tasks(plan: dict[str, Any]) -> dict[str, Any]:
    tasks = []
    for step in plan["steps"]:
        task: dict[str, Any] = {
            "id": "task-%s" % step["id"],
            "step_id": step["id"],
            "title": step["title"],
            "description": step["description"],
            "depends_on": ["task-%s" % d for d in step["depends_on"]],
            "status": "pending",
        }
        ar = step.get("action_ref")
        if ar is not None:
            task["action_ref"] = ar
        ap = step.get("action_parameters")
        if ap is not None:
            task["action_parameters"] = ap
        tasks.append(task)
    execution_order = _execution_order_for_tasks(tasks)
    return {
        "plan": plan,
        "tasks": tasks,
        "execution_order": execution_order,
        "run_id": str(uuid.uuid4()),
    }


def merge_plan_with_goal(plan: dict[str, Any], goal: str) -> dict[str, Any]:
    out = dict(plan)
    out["goal"] = goal.strip() or out.get("goal", "")
    return out
