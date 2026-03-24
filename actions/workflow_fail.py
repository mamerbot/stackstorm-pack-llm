# Copyright 2026 Emergent / Paperclip contributors
# SPDX-License-Identifier: MIT

from st2actions.runners.pythonrunner import Action


class WorkflowFail(Action):
    def run(self, message):
        raise ValueError(message or "workflow failed")
