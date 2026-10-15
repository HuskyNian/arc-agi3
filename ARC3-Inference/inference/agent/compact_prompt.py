"""Concise API contract without a mandatory per-turn reasoning checklist."""


WORKSPACE_GUIDANCE = (
    "\nData persistence: workspace.put(key, value, scope='level') and "
    "workspace.get(key, default=None, scope='level') store/load JSON data (tuples load as lists). "
    "Scopes: 'game' survives levels, 'level' survives resets but clears on level change, "
    "'observation' clears after any real action, including RESET. Use observation for current plans; "
    "game for reusable rules. Loads are copies; put again to save edits. "
    "workspace.keys(scope=...), delete(key, scope=...), clear(scope=...), info() manage storage. "
    "Limits: 128 entries, 2 MB total, 512 KB/entry. Optional put(..., expected_version=workspace.info()['version']) "
    "rejects writes based on an older observation. Only explicit writes persist; a later error/timeout does not undo them.\n"
)

BACKTEST_GUIDANCE = (
    "\nOptional rule check: backtest(predict, observe, indices=None, limit=32, max_examples=3). "
    "predict(before_frame, action_display) returns a nonempty dict of predicted fields or None for unsupported actions; "
    "observe(frame) returns the same observable fields. Example shapes: {'player': [row, col], 'key_present': True}. "
    "It checks the latest eligible transitions in the current level (limit 1..64; indices are zero-based in transitions), "
    "skipping RESET, automatic, terminal and cross-level transitions. It returns counts, tested indices, field coverage "
    "and up to 3 counterexamples/errors. Callbacks cannot act or write workspace; prints are suppressed. "
    "Compare meaningful dynamic fields; consistency on a sample is not proof of a complete model. "
    "Use when testing a rule, not on every turn.\n"
)

COMPACT_SUMMARY = (
    "Summarize for continuation without tools or actions: supported rules and evidence, counterexamples, "
    "unresolved hypotheses, current state/plan, and saved workspace keys or reusable functions. "
    "Preserve details needed to resume; omit repeated narration and superseded guesses."
)


def build_compact_prompt(*, tool_output_tokens, python_timeout, persistent_scope,
                         retain_imports, workspace, backtest, animation, timeline,
                         reset, undo, memory, prefix=""):
    text = """You solve multi-level grid puzzle games using the python tool.
Complete all levels within the run budget. Avoid unnecessary actions, but test uncertain mechanics when that enables progress.
Use code for calculations and search when useful. Once evidence supports an action, execute it; do not repeatedly restate the board or plan.
Build a simulator only when it helps. On a failed prediction, inspect a concrete counterexample or test the uncertain rule. Reuse supported mechanics across levels, checking new elements.

Python API:
- current_frame: .ascii (newline-separated letter grid), .step, .level, .shape, .segmentation. The current image, if attached, shows the same board. Process cells or objects in code; print only small results/crops.
- segmentation is {'nodes': [...], 'adjacency_list': [[id,id], ...]}. Nodes: id, color, pixels, boundary (outer-perimeter [row,col] corners), children (enclosed node ids), hash (color/shape up to rotation), pose_hash (rotation-sensitive), shape_hash (color-independent), rotation, rotational_symmetry. Nodes are same-color 4-connected components, not guaranteed game entities. IDs/hashes do not establish persistent identity.
- history entries have .action, .frame (after action), .result. history[-1].frame is current_frame. transitions entries have .action, .before_frame, .after_frame (.frame alias), .result; last_transition is the latest. previous_frame is the latest action's before-frame. A refused action adds no transition.
- frame_diff(before=None, after=None) defaults to previous_frame/current_frame. It returns changed_cell_count and moved/rotated/appeared/disappeared/changed_color/resized lists. Component matches are hypotheses; inspect cells when ambiguous.
- valid_actions lists available controls. action(['LEFT', ...]) executes a sequence; clicks use {'action':'MOUSE','row':r,'col':c}, zero-based. SPACE is game-specific. Action displays in history include click coordinates.
- action() refreshes current_frame, previous_frame, history, transitions, valid_actions, and last_action_call_result before returning. Loops and multiple action calls are allowed; check actual effects and stop a plan on a mismatch. Guards can refuse or stop batches; use executed_count/stop_reason, not requested length.
- game_over means attempt failed and the level auto-resets; level_completed means next level; done/run_complete means game won. Stop acting in this snippet after any of these flags. A fatal action and automatic RESET are separate history transitions.
- board_changed includes all cells; gameplay_changed ignores a border margin and is only a heuristic. Unchanged pixels can hide state changes. Edge bars may track a budget; do not assume every edge object is HUD.
- Python calls have fresh local variables. Use print() or a final expression for compact results. Inspection uses runtime but no game actions. Imports: bisect, collections, copy, difflib, fractions, functools, heapq, itertools, json, math, operator, random, re, statistics, string. No file I/O.
"""
    if reset:
        text += "- RESET restarts only the current level and costs an action; prior actions still count. It must be the first game action in a snippet.\n"
    if undo:
        text += "- UNDO, when available, reverses an action; verify what it restores. It cannot recover a failed attempt.\n"
    if animation:
        text += "- last_animation_frames provides ordered frames of the most recent action's animation (empty for a single frame). Aliases refresh after action().\n"
        if timeline:
            text += "- last_animation_timeline is {'action', 'frames', 'steps'}; each changed step has step/changed/bbox and changes or color transitions.\n"
    if persistent_scope:
        scope = {"game": "this game, across levels", "levelup": "this level", "turn": "this analyzer turn"}[persistent_scope]
        text += f"\nPlain top-level functions are retained for {scope}. Reuse or redefine them. "
        text += "Use literal defaults, no decorators/annotations; dependencies must be provided globals or retained functions, or passed as arguments. "
        text += ("Explicit imports used by retained functions are restored.\n" if retain_imports
                 else "Put required imports inside retained functions.\n")
    else:
        text += "\nFunction definitions do not persist; redefine needed helpers.\n"
    if workspace:
        text += WORKSPACE_GUIDANCE
    if backtest:
        text += BACKTEST_GUIDANCE
    if memory:
        text += "\nKeep supported rules separate from hypotheses in the memory sections; update only when evidence changes.\n"
    text += (f"\nEach Python call is limited to {python_timeout}s; tool output to about {tool_output_tokens} tokens. "
             "Save useful intermediate data before expensive work. "
             "Use the provided python tool-call format directly, without prose wrappers or markdown fences.\n")
    return (prefix + "\n" if prefix else "") + text
