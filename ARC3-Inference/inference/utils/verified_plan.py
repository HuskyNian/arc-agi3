"""Bounded forward execution with per-step prediction checks.

This module is also embedded into the isolated Python subprocess.
"""
import copy
import json
import math


def _plan_json(value, depth=0):
    if depth > 24:
        raise ValueError('prediction nesting exceeds 24')
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple):
        return [_plan_json(v, depth+1) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: _plan_json(v, depth+1) for k, v in value.items()}
    raise ValueError('predictions must be finite JSON with string keys')


def _plan_fields(value):
    if type(value) is not dict or not 1 <= len(value) <= 32:
        raise ValueError('return a nonempty dict of at most 32 observable fields')
    if any(type(k) is not str or not k or len(k) > 80 for k in value):
        raise ValueError('field names must be nonempty strings of at most 80 characters')
    value = _plan_json(value)
    if len(json.dumps(value)) > 8192:
        raise ValueError('observable fields exceed 8192 characters')
    return value


def run_verified_plan(actions, predict, observe, *, start, get_frame, act, check):
    """check invokes a read-only callback; act uses the existing guarded action API."""
    if not isinstance(actions, list) or not 1 <= len(actions) <= 16:
        raise ValueError('execute_plan requires 1..16 actions; split longer plans')
    if not callable(predict) or not callable(observe):
        raise TypeError('predict and observe must be callable')
    if (not isinstance(start, (tuple, list)) or len(start) != 2
            or any(type(v) is not int for v in start)):
        raise ValueError('start must be (level, step) from the planning frame')
    actions = copy.deepcopy(actions)
    frame = get_frame()
    report = dict(status='complete', requested=len(actions), executed=0, verified=0,
                  start=list(start), scope='predicted_fields_only')
    if frame is None or [frame.level, frame.step] != list(start):
        return dict(report, status='stale_plan')
    # A RESET invalidates the planning frame; use action(['RESET']) separately.
    if any(a['action'].upper() in ('RESET', 'ACTION0') for a in actions):
        raise ValueError('RESET must be separate; plan from the returned reset frame')
    for index, action_spec in enumerate(actions):
        before = get_frame()
        report['index'] = index
        report['action'] = action_spec
        report['before'] = [before.level, before.step]
        try:
            predicted = _plan_fields(check(predict, copy.deepcopy(before), copy.deepcopy(action_spec)))
            # Validate extraction before spending an action as well as afterwards.
            current = _plan_fields(check(observe, copy.deepcopy(before)))
            if not predicted.keys() <= current.keys():
                raise ValueError('observe must expose all predicted fields')
        except Exception as exc:
            return dict(report, status='prediction_error', detail=str(exc)[:240])
        outcome = act([action_spec])  # Existing terminal/no-op/death guards still apply.
        if not outcome.get('executed'):
            return dict(report, status='blocked', reason=outcome.get('stop_reason', 'not_executed'))
        report['executed'] += 1
        after = get_frame()
        for flag in ('run_complete', 'done', 'level_completed', 'game_over'):
            if outcome.get(flag):
                return dict(report, status='boundary', reason=flag)
        if after.level != before.level:
            return dict(report, status='boundary', reason='level_changed')
        try:
            actual = _plan_fields(check(observe, copy.deepcopy(after)))
        except Exception as exc:
            return dict(report, status='observation_error', detail=str(exc)[:240])
        differences = [k for k in predicted if k not in actual or
                       json.dumps(predicted[k], sort_keys=True) != json.dumps(actual[k], sort_keys=True)]
        if differences:
            def preview(value):
                return json.dumps(value, sort_keys=True)[:240]
            return dict(report, status='mismatch', after=[after.level, after.step],
                        differences=[dict(field=k, expected=preview(predicted[k]),
                                          actual=preview(actual[k]) if k in actual else '<missing>')
                                     for k in differences[:3]])
        report['verified'] += 1
        if outcome.get('stop_reason'):
            return dict(report, status='blocked', reason=outcome['stop_reason'])
    return report
