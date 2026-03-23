# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: Apache-2.0

from lib.plan_model import (
    PlanValidationError,
    merge_plan_with_goal,
    parse_plan_json,
    template_plan_from_goal,
    validate_plan,
)

from st2actions.runners.pythonrunner import Action


class PlanFromGoal(Action):
    def run(self, goal, structured_plan_json=None, override_goal=True):
        if not isinstance(goal, str) or not goal.strip():
            return False, "goal must be a non-empty string"
        g = goal.strip()
        if structured_plan_json:
            if not isinstance(structured_plan_json, str) or not structured_plan_json.strip():
                return False, "structured_plan_json must be a non-empty string when provided"
            try:
                parsed = parse_plan_json(structured_plan_json)
                plan = validate_plan(parsed)
            except PlanValidationError as exc:
                return False, str(exc)
            if override_goal:
                plan = merge_plan_with_goal(plan, g)
            return True, plan
        return True, template_plan_from_goal(g)
