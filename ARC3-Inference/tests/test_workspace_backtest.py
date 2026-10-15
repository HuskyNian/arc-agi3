"""Behavioral tests use real isolated subprocesses; no model or GPU required."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inference.agent.workspace import Workspace
from inference.agent.python_tool_sandbox import run_sandboxed_python
from inference.agent.tool_agent import ToolAgent, _build_system_prompt
from inference.agent.runtime_state import Frame, HistoryEntry, write_runtime_state


def frame(x=0, step=0, level=1):
    return dict(ascii="." * x + "R" + "." * (3 - x), step=step, level=level,
                shape=[1, 4], grid=[[0] * x + [2] + [0] * (3 - x)])


def state():
    return dict(current_frame=frame(2, 2), valid_actions=["RIGHT"], history=[
        dict(action="", frame=frame(), result={}),
        dict(action="RIGHT", frame=frame(1, 1), result={}),
        dict(action="RIGHT", frame=frame(2, 2), result={}),
    ])


OBSERVE = "def observe(f):\n    return {'x': f.ascii.index('R')}\n"
PREDICT = "def predict(f, a):\n    return {'x': f.ascii.index('R') + 1}\n"


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.w = Workspace()
        self.w.sync(level=1, observation=0)

    def put(self, key, value, scope="level", **kw):
        return self.w.handle(dict(op="put", key=key, value=value, scope=scope, **kw))

    def get(self, key, scope="level"):
        return self.w.handle(dict(op="get", key=key, scope=scope))

    def test_copies_not_aliases(self):
        v = {'path': [(1, 2)]}
        self.put('plan', v)
        v['path'].clear()
        loaded = self.get('plan')
        self.assertEqual(loaded, {'path': [[1, 2]]})
        loaded['path'].clear()
        self.assertEqual(self.get('plan'), {'path': [[1, 2]]})

    def test_scope_invalidation_and_isolation(self):
        for scope in self.w.SCOPES:
            self.put('x', scope, scope)
        self.w.sync(level=1, observation=1)  # Includes a visually unchanged action/reset.
        self.assertIsNone(self.get('x', 'observation'))
        self.assertEqual(self.get('x'), 'level')
        self.w.sync(level=2, observation=2)
        self.assertIsNone(self.get('x'))
        self.assertEqual(self.get('x', 'game'), 'game')
        self.assertIsNone(Workspace().handle(dict(op='get', key='x', scope='game')))

    def test_bad_writes_are_atomic(self):
        self.put('x', 12)
        for v in [float('nan'), {1: 'bad'}, {1, 2}, lambda: 1, 'x' * 512001]:
            with self.assertRaises(ValueError):
                self.put('x', v)
            self.assertEqual(self.get('x'), 12)
        recursive = []; recursive.append(recursive)
        with self.assertRaises(ValueError):
            self.put('x', recursive)

    def test_capacity_and_delete(self):
        self.w = Workspace(max_bytes=200, max_entries=1)
        self.put('x', 12)
        with self.assertRaises(ValueError):
            self.put('y', 12)
        with self.assertRaises(ValueError):
            self.put('x', 'z' * 201)
        self.assertEqual(self.get('x'), 12)
        self.assertTrue(self.w.handle(dict(op='delete', key='x')))
        self.put('y', 13)
        self.assertEqual(self.w.handle(dict(op='keys')), ['y'])
        self.w.handle(dict(op='clear'))
        self.assertEqual(self.w.handle(dict(op='info'))['bytes'], 0)

    def test_stale_write_rejected(self):
        version = self.w.handle(dict(op='info'))['version']
        self.w.sync(level=1, observation=1)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.put('plan', [1], expected_version=version)
        self.assertIsNone(self.get('plan'))


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace()
        self.workspace.sync(level=1, observation=2)
        self.actions = []

    def action(self, actions, **kwargs):
        self.actions.extend(actions)
        self.workspace.sync(level=1, observation=3)
        return {'action_result': {'executed': True}, 'state': state()}

    def run_code(self, code, **kwargs):
        return run_sandboxed_python(
            code=code, timeout_seconds=kwargs.pop('timeout_seconds', 3),
            initial_state=kwargs.pop('initial_state', state()), action_handler=self.action,
            workspace_handler=self.workspace.handle, backtest_enabled=True, **kwargs)

    def result(self, code, **kwargs):
        r = self.run_code(code, **kwargs)
        self.assertFalse(r.get('error'), r)
        return r['result']

    def test_persist_across_subprocesses_without_implicit_locals(self):
        self.result("CUR=[1,2]\nworkspace.put('CUR', CUR)")
        self.assertEqual(self.result("workspace.get('CUR')"), [1, 2])
        self.assertIn('NameError', self.run_code('CUR')['error'])

    def test_explicit_write_survives_exception_and_timeout(self):
        self.assertIn('ZeroDivisionError', self.run_code("workspace.put('x', 42)\n1/0")['error'])
        self.assertEqual(self.result("workspace.get('x')"), 42)
        r = self.run_code("workspace.put('x', 43)\nwhile True: pass", timeout_seconds=1)
        self.assertTrue(r['error'])
        self.assertEqual(self.result("workspace.get('x')"), 43)

    def test_invalid_data_is_not_silently_stringified(self):
        r = self.run_code("workspace.put('x', {1: 'no'})")
        self.assertIn('ValueError', r['error'])
        self.assertIsNone(self.result("workspace.get('x')"))

    def test_observation_clears_inside_same_snippet(self):
        code = "workspace.put('plan', [1], scope='observation')\naction('RIGHT')\nworkspace.get('plan', scope='observation')"
        self.assertIsNone(self.result(code))
        self.assertEqual(len(self.actions), 1)

    def test_retained_rule_can_read_workspace(self):
        code = ("workspace.put('dx', 1, scope='game')\n" + OBSERVE +
                "def predict(f, a):\n    return {'x': f.ascii.index('R') + workspace.get('dx', scope='game')}\n")
        r = self.run_code(code, kept_functions=[], retain_imports=True)
        self.assertFalse(r['error'], r)
        kept = [x['source'] for x in r['keepable_functions']]
        report = self.result("backtest(predict, observe)", kept_functions=kept, retain_imports=True)
        self.assertEqual(report['passed'], 2)
        self.assertEqual(report['status'], 'consistent_on_sample')
        self.assertEqual(report['fields'], {'x': 2})

    def test_counterexample_then_corrected_rule(self):
        bad = self.result(OBSERVE + PREDICT.replace('+ 1', '+ 2') + 'backtest(predict, observe)')
        self.assertEqual(bad['failed'], 2)
        self.assertEqual(bad['examples'][0]['differences']['x'], {'predicted': 2, 'observed': 1})
        good = self.result(OBSERVE + PREDICT + 'backtest(predict, observe)')
        self.assertEqual(good['failed'], 0)
        self.assertEqual(good['passed'], 2)

    def test_empty_unsupported_and_missing_fields_not_success(self):
        for body, expected in [('{}', 'model_error'), ('None', 'no_checks'), ("{'missing': 1}", 'model_error')]:
            report = self.result(OBSERVE + f'def predict(f,a): return {body}\nbacktest(predict, observe)')
            self.assertEqual(report['status'], expected)
            self.assertEqual(report['passed'], 0)

    def test_live_actions_and_workspace_writes_blocked_in_callbacks(self):
        for call in ["action('RIGHT')", "workspace.put('x', 1)", "workspace.clear()"]:
            report = self.result(OBSERVE + f'def predict(f,a):\n    {call}\n    return {{"x": 1}}\nbacktest(predict, observe)')
            self.assertEqual(report['status'], 'model_error')
            self.assertIn('read-only', report['examples'][0]['error'])
        self.assertEqual(self.actions, [])
        self.assertIsNone(self.result("workspace.get('x')"))
        # The latch is released even after a failed backtest.
        self.result(OBSERVE + 'def predict(f,a): return {}\nbacktest(predict,observe)\naction("RIGHT")')
        self.assertEqual(len(self.actions), 1)

    def test_mutating_supplied_frames_does_not_change_history(self):
        code = OBSERVE + "def predict(f,a):\n    f.ascii='BAD'\n    return {'x':1}\nbacktest(predict,observe)\nhistory[0].frame.ascii"
        self.assertEqual(self.result(code), 'R...')

    def test_bounded_selection_errors_and_prints(self):
        code = OBSERVE + "def predict(f,a):\n    print('noise'*10000)\n    return {'x': 999}\n"
        r = self.run_code(code + 'backtest(predict,observe,limit=1,max_examples=1)')
        self.assertFalse(r['error'], r)
        self.assertEqual(r['result']['indices'], [1])
        self.assertEqual(len(r['result']['examples']), 1)
        self.assertNotIn('noise', r['stdout'])
        for args in ['limit=0', 'limit=65', 'indices=[-1]', 'indices=[99]']:
            self.assertIn('ValueError', self.run_code(OBSERVE + PREDICT + f'backtest(predict,observe,{args})')['error'])

    def test_skip_boundaries_resets_and_terminal_frames(self):
        s = state()
        s['history'].extend([
            dict(action='RESET', frame=frame(0, 3), result={}),
            dict(action='RIGHT', frame=frame(1, 4), result={'game_over': True}),
            dict(action='RESET', frame=frame(0, 5), result={'automatic': True}),
            dict(action='RIGHT', frame=frame(1, 6, 2), result={'level_completed': True}),
        ])
        report = self.result(OBSERVE + PREDICT + 'backtest(predict,observe)', initial_state=s)
        self.assertEqual(report['tested'], 2)
        self.assertEqual(sum(report['skipped'].values()), 4)

    def test_field_count_and_nonfinite_values_are_rejected(self):
        for expression in ["{str(i): i for i in range(33)}", "{'x': float('nan')}"]:
            code = f'def observe(f): return {expression}\ndef predict(f,a): return observe(f)\nbacktest(predict,observe)'
            report = self.result(code)
            self.assertEqual(report['status'], 'model_error')
            self.assertEqual(report['tested'], 0)

    def test_missing_before_frame_and_empty_history_not_vacuous_success(self):
        s = state()
        s['history'] = s['history'][1:2]  # An action without its before frame.
        report = self.result(OBSERVE + PREDICT + 'backtest(predict,observe)', initial_state=s)
        self.assertEqual(report['status'], 'no_checks')
        self.assertEqual(report['skipped'], {'missing_frame': 1})
        s['history'] = []
        self.assertEqual(self.result(OBSERVE + PREDICT + 'backtest(predict,observe)', initial_state=s)['status'], 'no_checks')

    def test_model_exception_does_not_stop_later_checks(self):
        code = OBSERVE + "def predict(f,a):\n    if f.step == 0: raise ValueError('bad model')\n    return {'x': f.ascii.index('R') + 1}\nbacktest(predict,observe)"
        report = self.result(code)
        self.assertEqual(report['errors'], 1)
        self.assertEqual(report['passed'], 1)

    def test_mismatched_input_does_not_change_real_action_cost(self):
        self.result(OBSERVE + PREDICT.replace('+ 1', '+ 2') + 'backtest(predict,observe)')
        self.assertEqual(self.actions, [])
        self.assertEqual(self.workspace.handle(dict(op='info'))['version'], 1)

    def test_feature_flags_remove_apis(self):
        r = run_sandboxed_python(code='workspace.info()', timeout_seconds=3,
                                 initial_state=state(), action_handler=self.action)
        self.assertIn('NameError', r['error'])
        r = run_sandboxed_python(code='backtest(None,None)', timeout_seconds=3,
                                 initial_state=state(), action_handler=self.action)
        self.assertIn('NameError', r['error'])


class AgentIntegrationTests(unittest.TestCase):
    def test_state_refresh_and_new_game_clear_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'game1' / 'state.json'
            f = Frame(((0, 1),), 1, 1)
            write_runtime_state(p, current_frame=f, history=[HistoryEntry('', f)])
            agent = ToolAgent(model='test-model')
            agent._run_python_tool(p, {'code': "workspace.put('rule', 1, scope='game')\nworkspace.put('layout', 2)\nworkspace.put('plan', 3, scope='observation')"})
            f2 = Frame(((1, 0),), 2, 2)
            write_runtime_state(p, current_frame=f2, history=[HistoryEntry('', f), HistoryEntry('RIGHT', f2)])
            r = agent._run_python_tool(p, {'code': "[workspace.get('rule', scope='game'), workspace.get('layout'), workspace.get('plan',scope='observation')]"})
            self.assertIn('[1, None, None]', r.content)
            p2 = Path(td) / 'game2' / 'state.json'
            write_runtime_state(p2, current_frame=f, history=[HistoryEntry('', f)])
            r = agent._run_python_tool(p2, {'code': "workspace.keys(scope='game')"})
            self.assertEqual(json.loads(r.content)['stdout'].strip(), '[]')

    def test_compact_prompt_has_contract_without_mandatory_reasoning(self):
        with patch.dict('os.environ', {'ARC3_COMPACT_PROMPT': '1', 'ARC3_MEMORY_SECTIONS': 'off',
                                       'ARC3_WORKSPACE': '1', 'ARC3_RULE_BACKTEST': '1'}):
            text = _build_system_prompt(tool_output_tokens=3072)
            self.assertIn('workspace.put', text)
            self.assertIn('backtest(', text)
            self.assertIn('game_over means attempt failed', text)
            self.assertNotIn('Do not ration tool calls', text)
            self.assertNotIn('ALWAYS GIVE', text)
            agent = ToolAgent(model='test-model')
            prompt = agent._build_user_prompt(1, valid_actions=['RIGHT'], current_frame=Frame(((0,),), 1, 1))
            self.assertNotIn('Only tool:', prompt)
            self.assertNotIn('backtest(', prompt)  # No per-turn workflow demand.
            self.assertLess(len(prompt), 500)
        with patch.dict('os.environ', {'ARC3_WORKSPACE': '0', 'ARC3_RULE_BACKTEST': '0'}):
            text = _build_system_prompt(tool_output_tokens=3072)
            self.assertNotIn('workspace.put', text)
            self.assertNotIn('backtest(', text)


if __name__ == '__main__':
    unittest.main()
