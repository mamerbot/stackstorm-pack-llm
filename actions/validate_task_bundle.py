# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

from lib.plan_model import TaskBundleValidationError, validate_task_bundle

from st2actions.runners.pythonrunner import Action


class ValidateTaskBundle(Action):
    def run(self, bundle):
        try:
            normalized = validate_task_bundle(bundle)
        except TaskBundleValidationError as exc:
            return False, str(exc)
        return True, normalized
