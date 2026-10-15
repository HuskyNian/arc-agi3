"""Read-only, bounded transition checks; also embedded into the Python sandbox.

No project imports or future statements: the source is embedded verbatim.
"""
import json
import copy


def _rule_json(value):
    # Reject arbitrary objects, non-string keys and nonfinite numbers rather
    # than turning them into apparently comparable strings.
    def clean(v, depth=0):
        if depth > 32:
            raise ValueError("prediction is nested too deeply")
        if v is None or type(v) in (str, bool, int, float):
            return v
        if type(v) in (tuple, list):
            return [clean(x, depth + 1) for x in v]
        if type(v) is dict and all(type(k) is str for k in v):
            return {k: clean(x, depth + 1) for k, x in v.items()}
        raise ValueError("predict/observe must return JSON data with string keys")
    value = clean(value)
    encoded = json.dumps(value, allow_nan=False, sort_keys=True)
    if len(encoded) > 32768:
        raise ValueError("prediction/observation too large; return a few meaningful fields")
    return value


def _rule_preview(value):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return value if len(text) <= 240 else {"preview": text[:237] + "...", "truncated": True}


def check_transitions(predict, observe, transitions, *, level, indices=None,
                      limit=32, max_examples=3):
    """Compare predicted fields with observed fields, never a whole simulator verdict.

    predict(before_frame, action_display) -> nonempty dict or None (unsupported).
    observe(after_frame) -> dict. Only predicted top-level fields are compared.
    The caller must prevent live actions while callbacks run.
    """
    if not callable(predict) or not callable(observe):
        raise TypeError("backtest expects predict(before, action) and observe(frame) functions")
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError("limit must be 1..64")
    if type(max_examples) is not int or not 1 <= max_examples <= 3:
        raise ValueError("max_examples must be 1..3")
    if indices is None:
        chosen = list(range(len(transitions)))
    else:
        chosen = list(indices)
        if any(type(i) is not int or not 0 <= i < len(transitions) for i in chosen):
            raise ValueError("indices must be nonnegative indices into transitions")
        chosen = sorted(set(chosen))
    skipped = {}
    candidates = []
    for i in chosen:
        t = transitions[i]
        reason = None
        if t.before_frame is None or t.after_frame is None:
            reason = "missing_frame"
        elif t.before_frame.level != level or t.after_frame.level != level:
            reason = "other_level_or_boundary"
        elif t.action.upper() == "RESET" or t.result.get("automatic"):
            reason = "reset_or_automatic"
        elif any(t.result.get(k) for k in ("game_over", "level_completed", "run_complete", "done")):
            reason = "terminal"
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            candidates.append(i)
    selected = candidates[-limit:]
    report = dict(status="no_checks", eligible=len(candidates), tested=0, passed=0,
                  failed=0, errors=0, unsupported=0, indices=selected, fields={},
                  skipped=skipped, examples=[], scope="predicted_fields_only")
    for i in selected:
        t = transitions[i]
        detail = dict(index=i, step=t.before_frame.step, action=t.action)
        try:
            expected = _rule_json(predict(copy.deepcopy(t.before_frame), t.action))
            if expected is None:
                report["unsupported"] += 1
                continue
            if not isinstance(expected, dict) or not expected:
                raise ValueError("predict must return a nonempty dict or None (unsupported)")
            actual = _rule_json(observe(copy.deepcopy(t.after_frame)))
            if not isinstance(actual, dict):
                raise ValueError("observe must return a dict")
            missing = expected.keys() - actual.keys()
            if missing:
                raise ValueError("observe missing predicted fields: " + ", ".join(sorted(missing)))
            if len(report["fields"].keys() | expected.keys()) > 32 or any(len(k) > 80 for k in expected):
                raise ValueError("use at most 32 short named observation fields")
            differences = []
            for key, value in expected.items():
                different = json.dumps(value, sort_keys=True) != json.dumps(actual[key], sort_keys=True)
                differences.append((key, different))
            report["tested"] += 1
            for key, _ in differences:
                report["fields"][key] = report["fields"].get(key, 0) + 1
            wrong = [key for key, different in differences if different]
            if wrong:
                report["failed"] += 1
                detail["differences"] = {k: {"predicted": _rule_preview(expected[k]),
                                             "observed": _rule_preview(actual[k])} for k in wrong[:3]}
            else:
                report["passed"] += 1
                continue
        except Exception as exc:
            report["errors"] += 1
            detail["error"] = (type(exc).__name__ + ": " + str(exc))[:300]
        if len(report["examples"]) < max_examples:
            report["examples"].append(detail)
    if report["errors"]:
        report["status"] = "model_error"
    elif report["failed"]:
        report["status"] = "counterexample"
    elif report["tested"]:
        report["status"] = "consistent_on_sample"
    return report
