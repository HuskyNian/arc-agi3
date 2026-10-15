"""Exercise the notebook's source discovery without a Kaggle runtime."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


NOTEBOOK = Path(__file__).resolve().parents[2] / 'arc-agi-3-m2-my.ipynb'


class SourceLoadingTests(unittest.TestCase):
    def setUp(self):
        self.notebook = json.loads(NOTEBOOK.read_text())
        setup = ''.join(self.notebook['cells'][2]['source'])
        start = setup.index('# Keep the original bundle')
        end = setup.index('# True only inside', start)
        self.discovery = setup[start:end].replace('Path("/kaggle/input")', 'input_root')

    def source(self, root):
        for name in ['ARC3-Inference/inference/agent/workspace.py',
                     'ARC3-Inference/inference/agent/compact_prompt.py',
                     'ARC3-Inference/inference/utils/rule_backtest.py']:
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        (root / 'tufa-arc-agi-framework/src/taaf').mkdir(parents=True)

    def discover(self, root, override=''):
        scope = dict(Path=Path, os=os, input_root=root, ORIG_BUNDLE_DIR='/original-bundle')
        with patch.dict(os.environ, {'ARC3_SOURCE_ROOT': override}):
            exec(self.discovery, scope)
        return scope['SOURCE_ROOT']

    def test_unique_dataset_and_explicit_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); one = root / 'datasets' / 'owner' / 'project'
            self.source(one)
            self.assertEqual(self.discover(root), one.resolve())
            two = root / 'second'; self.source(two)
            with self.assertRaisesRegex(RuntimeError, 'found 2'):
                self.discover(root)
            self.assertEqual(self.discover(root, str(two)), two.resolve())

    def test_missing_dataset_fails_before_loading_old_code(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, 'found 0'):
                self.discover(Path(td))
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                self.discover(Path(td), td)

    def test_edited_cells_are_python_and_no_patch(self):
        for i in [2, 8]:
            source = ''.join(self.notebook['cells'][i]['source'])
            ast.parse(source)
            self.assertNotIn('harness-changes.patch', source)
        setup = ''.join(self.notebook['cells'][2]['source'])
        for flag in ['ARC3_WORKSPACE', 'ARC3_RULE_BACKTEST', 'ARC3_COMPACT_PROMPT']:
            self.assertIn(f"'{flag}': '1'", setup)


if __name__ == '__main__':
    unittest.main()
