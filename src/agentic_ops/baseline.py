"""Frozen A baseline: unique authenticated candidate, unchanged tag, no model."""
import json
from .contracts import Facts, ActionRequest


class BaselineDiagnosticProvider:
    def __init__(self, evidence_provider):
        self.evidence = evidence_provider

    def collect(self, trigger):
        raw = self.evidence.collect(trigger)
        action = None
        if len(raw.pull_failures) == 1:
            failure = raw.pull_failures[0]
            checks = [json.loads(item.value) for item in raw.items
                      if item.name == 'authenticated-registry-manifest']
            checks = [c for c in checks if c.get('container') == failure.container
                      and c.get('image') == failure.image]
            if len(checks) == 1:
                c = checks[0]
                candidates = c.get('verified_candidates')
                if (c.get('status') == 'missing' and c.get('candidate_status') == 'complete'
                        and isinstance(candidates, list) and len(candidates) == 1
                        and isinstance(candidates[0], str) and candidates[0].strip()):
                    action = ActionRequest('fix_image', {'image': candidates[0]})
        return Facts(raw.items, raw.groundedness, action,
                     'Deterministic unique-candidate baseline; independent execution policy still applies.',
                     raw.pull_failures)
