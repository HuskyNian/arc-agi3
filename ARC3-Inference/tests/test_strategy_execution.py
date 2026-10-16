import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inference.agent.python_tool_sandbox import run_sandboxed_python
from inference.agent.runtime_state import Frame, HistoryEntry, write_runtime_state
from inference.agent.runtime_state import RUNTIME_STATE_FILENAME
from inference.agent.strategy_monitor import StrategyMonitor
from inference.agent.tool_agent import ToolAgent, _build_system_prompt


RULE = """
def predict(f, a):
    return {'x': f.ascii.index('R') + 1}
def observe(f):
    return {'x': f.ascii.index('R')}
"""
CALL = "execute_plan(['RIGHT', 'RIGHT', 'RIGHT'], predict, observe, start=(1,0))"


class VerifiedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.x = 0; self.steps = 0; self.calls = []; self.events = []; self.history = []
        self.delta = 1; self.terminal = None; self.refuse = False
        self.history.append(dict(action='', frame=self.frame(), result={}))

    def frame(self):
        return dict(ascii='.'*self.x+'R'+'.'*(7-self.x), step=self.steps, level=1,
                    shape=[1,8], grid=[[0]*self.x+[2]+[0]*(7-self.x)])

    def state(self):
        return dict(current_frame=self.frame(), history=list(self.history), valid_actions=['RIGHT'])

    def action(self, actions, **kwargs):
        self.calls.append(actions)
        if self.refuse:
            result = dict(executed=False, stop_reason='known_noop', stop_detail='test refusal')
        else:
            self.steps += 1; self.x += self.delta
            result = dict(executed=True, executed_count=1, gameplay_changed=True)
            if self.terminal: result[self.terminal] = True
            self.history.append(dict(action='RIGHT', frame=self.frame(), result=result))
        return dict(action_result=result, state=self.state())

    def run_code(self, code, enabled=True, timeout=3):
        return run_sandboxed_python(code=code, timeout_seconds=timeout, initial_state=self.state(),
            action_handler=self.action, verified_plan_enabled=enabled, plan_event_handler=self.events.append)

    def test_matching_plan_runs_without_extra_model_calls(self):
        result = self.run_code(RULE+CALL)
        self.assertEqual(result['result']['verified'], 3)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(len(call)==1 for call in self.calls))
        self.assertEqual([e['event'] for e in self.events], ['start','finish'])

    def test_mismatch_discards_tail_and_latches_following_actions(self):
        self.delta = 2
        result = self.run_code(RULE+CALL+"\ntry:\n    action(['RIGHT'])\nexcept Exception:\n    action(['RIGHT'])")
        self.assertEqual(len(self.calls), 1)
        self.assertIn('PlanStoppedError', result['error'])
        self.assertEqual(self.events[-1]['status'], 'mismatch')
        self.assertEqual(self.events[-1]['executed'], 1)
        self.assertEqual(self.events[-1]['verified'], 0)
        # New snippet can inspect and use a revised prediction at the real state.
        result = self.run_code(RULE.replace('+ 1','+ 2')+
            "execute_plan(['RIGHT'], predict, observe, start=(1,1))")
        self.assertEqual(result['result']['status'], 'complete')

    def test_callbacks_cannot_spend_actions(self):
        result = self.run_code(RULE+"\ndef predict(f,a):\n    action(['RIGHT'])\n    return {'x': 1}\n"+CALL)
        self.assertEqual(result['result']['status'], 'prediction_error')
        self.assertEqual(self.calls, [])

    def test_callback_mutation_does_not_change_live_frame(self):
        result = self.run_code(RULE+"\ndef predict(f,a):\n    f.ascii='broken'\n    return {'x': 1}\n"+
            "execute_plan(['RIGHT'], predict, observe, start=(1,0))")
        # A mutable copy may be edited, or an immutable view may reject it;
        # either way the live state is never changed by the callback.
        self.assertIn(result['result']['status'], ('complete','prediction_error'))
        self.assertEqual(self.x, len(self.calls))

    def test_empty_nonfinite_or_missing_fields_fail_before_acting(self):
        for expr in ('{}', "{'x': float('nan')}", "{'missing': 1}"):
            result = self.run_code(RULE+f'\ndef predict(f,a): return {expr}\n'+CALL)
            self.assertEqual(result['result']['status'], 'prediction_error')
        self.assertEqual(self.calls, [])

    def test_terminal_events_stop_without_false_mismatch(self):
        for flag in ('level_completed','game_over','run_complete','done'):
            self.setUp(); self.terminal = flag
            result = self.run_code(RULE+CALL)
            self.assertEqual(result['result']['status'], 'boundary')
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(result['result']['reason'], flag)

    def test_existing_guard_refusal_still_stops_execution(self):
        self.refuse = True
        result = self.run_code(RULE+CALL)
        self.assertIn('KnownNoOpActionError', result['error'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.steps, 0)

    def test_reset_stale_plan_and_oversized_plan_do_not_act(self):
        result = self.run_code(RULE+CALL.replace('(1,0)', '(1,8)'))
        self.assertEqual(result['result']['status'], 'stale_plan')
        for actions in ("['RESET','RIGHT']", "['RIGHT']*17"):
            result = self.run_code(RULE+f'execute_plan({actions}, predict, observe, start=(1,0))')
            self.assertIn('ValueError', result['error'])
        self.assertEqual(self.calls, [])

    def test_disabled_api_and_timeout_preserve_action_accounting(self):
        result = self.run_code(RULE+CALL, enabled=False)
        self.assertIn('NameError', result['error'])
        result = self.run_code(RULE+"\ndef predict(f,a):\n    if f.step > 0:\n        while True: pass\n    return {'x': 1}\n"+CALL, timeout=1)
        self.assertIn('timed out', result['error'])
        self.assertEqual(len(result['action_results']), 1)
        self.assertEqual(self.steps, 1)


class MonitorTests(unittest.TestCase):
    def observation(self, monitor, **kw):
        return monitor.observe(**dict(dict(level=1,state_key='s',model_key='m',error='NameError: x'), **kw))

    def test_threshold_cooldown_and_evidence(self):
        m=StrategyMonitor()
        self.assertIsNone(self.observation(m)); self.assertIsNone(self.observation(m))
        event=self.observation(m)
        self.assertEqual(event['tool_calls'], [1,2,3])
        for _ in range(7): self.assertIsNone(self.observation(m))
        self.assertIsNotNone(self.observation(m))

    def test_no_trigger_on_successful_readonly_search_or_actions(self):
        m=StrategyMonitor()
        for _ in range(30):
            self.assertIsNone(self.observation(m,error=''))
            self.assertIsNone(self.observation(m,error='',actions=[dict(executed=True,gameplay_changed=False)]))

    def test_identical_readonly_results_trigger_but_changing_search_does_not(self):
        m=StrategyMonitor()
        for i in range(10):
            self.assertIsNone(self.observation(m,error='',output_key=str(i)))
        for _ in range(2):
            self.assertIsNone(self.observation(m,error='',output_key='repeated'))
        self.assertEqual(self.observation(m,error='',output_key='repeated')['kind'], 'repeated_identical_computation')

    def test_changed_state_code_level_or_boundary_breaks_streak(self):
        for change in (dict(state_key='new'),dict(model_key='new'),dict(level=2),
                       dict(actions=[dict(game_over=True,executed=True)])):
            m=StrategyMonitor()
            self.observation(m); self.observation(m)
            self.assertIsNone(self.observation(m,**change))

    def test_refusal_and_mismatch_have_specific_feedback(self):
        for kw, kind in ((dict(error='',actions=[dict(executed=False,stop_reason='known_noop')]),'repeated_guard_refusal'),
                         (dict(error='',plans=[dict(status='mismatch',differences=[dict(field='x',expected='1',actual='2')])]),'repeated_prediction_mismatch')):
            m=StrategyMonitor()
            self.observation(m,**kw); self.observation(m,**kw)
            self.assertEqual(self.observation(m,**kw)['kind'],kind)

    def test_host_modes_logging_and_game_isolation(self):
        for mode in ('off','shadow','on'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {
                'ARC3_STRATEGY_MONITOR':mode,'ARC3_VERIFIED_PLAN':'0'}):
                path=Path(td)/'state.json'; f=Frame(((0,),),0,1)
                write_runtime_state(path,current_frame=f,history=[HistoryEntry('',f)])
                agent=ToolAgent(model='test')
                for _ in range(3): result=agent._run_python_tool(path,dict(code='missing_function()'))
                self.assertEqual('strategy_feedback' in json.loads(result.content), mode=='on')
                log=path.parent/'strategy'/'state.jsonl'
                self.assertEqual(log.exists(),mode!='off')
                if mode!='off':
                    records=[json.loads(s) for s in log.read_text().splitlines()]
                    self.assertEqual(records[-1]['intervention']['tool_calls'],[1,2,3])
                other=Path(td)/'other'/'state.json'
                write_runtime_state(other,current_frame=f,history=[HistoryEntry('',f)])
                result=agent._run_python_tool(other,dict(code='missing_function()'))
                self.assertNotIn('strategy_feedback',json.loads(result.content))

    def test_new_prompt_only_describes_execution_api(self):
        with patch.dict('os.environ',{'ARC3_VERIFIED_PLAN':'1'}):
            text=_build_system_prompt(tool_output_tokens=3072)
            self.assertIn('execute_plan(',text)
            self.assertNotIn('workspace.put',text)
            self.assertNotIn('backtest(',text)
            self.assertIn('Do not ration tool calls',text)

    def test_agent_plan_report_survives_ignored_return_and_logs_per_game(self):
        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {
            'ARC3_STRATEGY_MONITOR':'on','ARC3_VERIFIED_PLAN':'1'}):
            root=Path(td); path=root/'artifacts'/f'game_p0_{RUNTIME_STATE_FILENAME}'
            f=Frame(((0,),),0,1); history=[HistoryEntry('',f)]
            write_runtime_state(path,current_frame=f,history=history)
            agent=ToolAgent(model='test'); calls=[]
            def step(arguments):
                calls.append(arguments)
                after=Frame(((1,),),2,1)  # Unexpected two-step advance.
                outcome=dict(executed=True,executed_count=1,gameplay_changed=True,
                             valid_actions=['RIGHT'],action_display='RIGHT',level=1)
                history.append(HistoryEntry('RIGHT',after,outcome))
                write_runtime_state(path,current_frame=after,history=history)
                return outcome
            agent._step_env_callback=step; agent._current_valid_actions=['RIGHT']
            result=agent._run_python_tool(path,dict(code="""
def predict(f,a): return {'step': f.step+1}
def observe(f): return {'step': f.step}
ignored = execute_plan(['RIGHT','RIGHT'], predict, observe, start=(1,0))
"""))
            payload=json.loads(result.content)
            self.assertEqual(len(calls),1)
            self.assertTrue(result.step_executed)
            self.assertEqual(payload['plan_reports'][0]['status'],'mismatch')
            log=root/'strategy'/'game_p0.jsonl'
            record=json.loads(log.read_text())
            self.assertEqual(record['executed'],1)
            self.assertEqual(record['tool_call'],1)
            self.assertEqual(record['plan_events'][-1]['status'],'mismatch')


if __name__=='__main__': unittest.main()
