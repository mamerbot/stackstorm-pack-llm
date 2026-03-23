# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

from lib.plan_model import (
    PlanValidationError,
    TaskBundleValidationError,
    plan_to_tasks,
    validate_plan,
    validate_task_bundle,
)

from st2actions.runners.pythonrunner import Action


class TasksFromPlan(Action):
    def run(self, plan):
        try:
            normalized = validate_plan(plan)
        except PlanValidationError as exc:
            return False, str(exc)
        try:
            bundle = plan_to_tasks(normalized)
            return True, validate_task_bundle(bundle)
        except TaskBundleValidationError as exc:
            return False, str(exc)
