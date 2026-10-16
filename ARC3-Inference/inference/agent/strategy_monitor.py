"""Conservative, per-game evidence tracking; no model calls or game actions."""
from collections import deque
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:20]


class StrategyMonitor:
    def __init__(self, threshold=3, cooldown=8):
        self.threshold = max(2, threshold)
        self.cooldown = max(1, cooldown)
        self.calls = 0
        self.level = None
        self.key = None
        self.streak = 0
        self.last_notice = -self.cooldown
        self.evidence = deque(maxlen=8)

    def observe(self, *, level, state_key, model_key, error='', actions=(), plans=(), output_key=''):
        self.calls += 1
        if level != self.level:
            self.level = level
            self.key = None
            self.streak = 0
            self.evidence.clear()
            self.last_notice = -self.cooldown
        if any(a.get(f) for a in actions for f in ('game_over', 'level_completed', 'done', 'run_complete')):
            self.key = None; self.streak = 0; self.evidence.clear()
            return None
        kind = detail = advice = ''
        # No inference from elapsed time, zero reward, pixels, or long reasoning.
        if plans and plans[-1].get('status') == 'mismatch':
            kind = 'repeated_prediction_mismatch'
            detail = json.dumps(plans[-1].get('differences', []), sort_keys=True)[:800]
            advice = 'Revise the contradicted prediction or its observation mapping before reusing this plan.'
        elif actions and not any(a.get('executed') for a in actions) and actions[-1].get('stop_reason'):
            kind = 'repeated_guard_refusal'
            a = actions[-1]
            detail = str((a.get('stop_reason'), a.get('blocked_action') or a.get('action_display')))[:400]
            advice = 'Inspect the refusal and current state; choose a different action or an evidence-supported override.'
        elif error and not any(a.get('executed') for a in actions):
            kind = 'repeated_tool_error'
            detail = error.strip().splitlines()[-1][:300]
            advice = 'Fix the failing call or use a different computation before repeating it.'
        elif output_key and not actions and not error:
            kind = 'repeated_identical_computation'
            detail = 'Identical code returned identical output without taking an action: ' + output_key
            advice = 'This computation reported no new result. Change its inputs/search limits, test a specific uncertainty, or execute a supported action.'
        if not kind:
            self.key = None; self.streak = 0; self.evidence.clear()
            return None
        key = fingerprint([kind, level, state_key, model_key, detail])
        if key != self.key:
            self.key = key; self.streak = 0; self.evidence.clear()
        self.streak += 1
        self.evidence.append(self.calls)
        if self.streak < self.threshold or self.calls-self.last_notice < self.cooldown:
            return None
        self.last_notice = self.calls
        return dict(kind=kind, tool_calls=list(self.evidence), count=self.streak,
                    detail=detail, advice=advice)
