"""Only setup selection/copy behavior; no native engine or dependency rebuild."""
import hashlib
from pathlib import Path
import tempfile
import unittest

CONTEXT = {}


class SetupToolOverlayTests(unittest.TestCase):
    def test_exact_extension(self):
        c=CONTEXT;names=c['names']
        old=c['old_select'](names);new=c['select'](names)
        self.assertEqual(set(new)-set(old),set(c['additional']))
        self.assertEqual(new,[n for n in names if n in set(old)|set(c['additional'])])

    def test_all_frozen_layer_files(self):
        c=CONTEXT
        required=set(c['prior_freeze']) & set(c['names'])
        self.assertTrue(required<=set(c['select'](c['names'])),sorted(required-set(c['select'](c['names']))))

    def test_copy_exact_public_bytes(self):
        c=CONTEXT;expected=c['select'](c['names'])
        with tempfile.TemporaryDirectory(prefix='ft-overlay-exact-') as directory:
            output=Path(directory);c['copy'](c['names'],output)
            actual=sorted(str(p.relative_to(output)) for p in output.rglob('*') if p.is_file())
            self.assertEqual(actual,sorted(expected))
            for name in actual:
                self.assertEqual((output/name).read_bytes(),(c['public']/name).read_bytes(),name)
            c['report']['copied']={n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in actual}

    def test_old_filter_preserved(self):
        c=CONTEXT
        names=['full_theory/example.py','tests_ft7/test_example.py','contracts/ft/example.json',
               'tools/evaluate_ft_example.py','tools/audit_ft_example.py','tools/compare_ft_example.py',
               'tools/prepare_workspace.py','tools/unregistered.py','PRIVATE_COMPANIONS.json',
               'baseline/example.py','docs/private.json','arbitrary/tool.py']+c['additional']
        self.assertEqual(set(c['select'](names)),set(c['old_select'](names))|set(c['additional']))
        for denied in names[7:12]:self.assertNotIn(denied,c['select'](names))

    def test_unsafe_overlay_path_rejected(self):
        with tempfile.TemporaryDirectory(prefix='ft-overlay-unsafe-') as directory:
            output=Path(directory)
            with self.assertRaisesRegex(ValueError,'unsafe'):
                CONTEXT['copy'](['full_theory/../private.py'],output)
            self.assertEqual(list(output.iterdir()),[])

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory(prefix='ft-overlay-existing-') as directory:
            output=Path(directory)
            with self.assertRaisesRegex(ValueError,'existing work is preserved'):
                CONTEXT['module'].prepare(None,None,output)
            self.assertEqual(list(output.iterdir()),[])
