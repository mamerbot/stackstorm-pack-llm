# Copyright 2026 Emtesseract / Paperclip contributors
# SPDX-License-Identifier: MIT

from lib.plan_model import PlanValidationError, parse_plan_json, validate_plan

from st2actions.runners.pythonrunner import Action


class NormalizePlanFromLlm(Action):
    def run(self, plan_json_str):
        if not isinstance(plan_json_str, str) or not plan_json_str.strip():
            return False, "plan_json_str must be a non-empty string"
        try:
            parsed = parse_plan_json(plan_json_str)
            plan = validate_plan(parsed)
        except PlanValidationError as exc:
            return False, str(exc)
        return True, plan
