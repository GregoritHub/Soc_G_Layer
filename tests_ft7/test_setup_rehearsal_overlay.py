"""New setup-only A3 gate; never invokes earlier accepted method suites."""
import hashlib,tempfile,unittest
from pathlib import Path

CONTEXT={}


class SetupContinuationOverlayTests(unittest.TestCase):
    def test_exact_one_path_extension(self):
        c=CONTEXT;names=c['names'];before=c['old_select'](names);after=c['select'](names)
        self.assertEqual(set(after)-set(before),{c['additional']})
        self.assertEqual(after,[n for n in names if n in set(before)|{c['additional']}])

    def test_all_frozen_public_files_selected(self):
        c=CONTEXT;required=set(c['prior'])&set(c['names'])
        self.assertTrue(required<=set(c['select'](c['names'])))
        self.assertIn('tools/evaluate_ft7_observed_field_reads.py',c['select'](c['names']))

    def test_copy_exact_bytes(self):
        c=CONTEXT;expected=c['select'](c['names'])
        with tempfile.TemporaryDirectory(prefix='ft-a3-copy-') as directory:
            output=Path(directory);c['copy'](c['names'],output)
            actual=sorted(p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file())
            self.assertEqual(actual,sorted(expected))
            for name in actual:self.assertEqual((output/name).read_bytes(),(c['public']/name).read_bytes())
            c['report']['copied']={n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in actual}

    def test_no_broad_tool_permission(self):
        c=CONTEXT;allowed=['tools/prepare_workspace.py','full_theory/x.py','tests_ft7/x.py','contracts/ft/x.json','tools/evaluate_ft_x.py',c['additional']]
        denied=['tools/continue_ft7_other.py','tools/continue_owned_rehearsal_closure.py.bak','PRIVATE_COMPANIONS.json','baseline/x.py','docs/private.json']
        self.assertEqual(c['select'](allowed+denied),allowed)

    def test_unsafe_path_rejected(self):
        with tempfile.TemporaryDirectory(prefix='ft-a3-unsafe-') as directory:
            output=Path(directory)
            with self.assertRaisesRegex(ValueError,'unsafe'):CONTEXT['copy'](['full_theory/../private.py'],output)
            self.assertEqual(list(output.iterdir()),[])

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory(prefix='ft-a3-existing-') as directory:
            output=Path(directory)
            with self.assertRaisesRegex(ValueError,'existing work is preserved'):CONTEXT['module'].prepare(None,None,output)
            self.assertEqual(list(output.iterdir()),[])
