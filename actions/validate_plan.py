# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

from lib.plan_model import PlanValidationError, validate_plan

from st2actions.runners.pythonrunner import Action


class ValidatePlan(Action):
    def run(self, plan):
        try:
            normalized = validate_plan(plan)
        except PlanValidationError as exc:
            return False, str(exc)
        return True, normalized
