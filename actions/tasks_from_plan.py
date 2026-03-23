# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

from lib.plan_model import PlanValidationError, plan_to_tasks, validate_plan

from st2actions.runners.pythonrunner import Action


class TasksFromPlan(Action):
    def run(self, plan):
        try:
            normalized = validate_plan(plan)
        except PlanValidationError as exc:
            return False, str(exc)
        return True, plan_to_tasks(normalized)
