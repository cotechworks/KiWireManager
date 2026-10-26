import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from kicad_import import discover, import_folder, parse_schematic, read_netlist, serialize


def schematic(*references):
    sheets = ''.join(f'(sheet (property "Sheetname" "child") (property "Sheetfile" {json.dumps(ref)}))' for ref in references)
    return '(kicad_sch (version 20250114) ' + sheets + ')'


class ImportTests(unittest.TestCase):
    def test_autosave_files_are_excluded_recursively(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'sub').mkdir()
            (base / 'main.kicad_sch').write_text(schematic(), encoding='utf-8')
            for name in ('_autosave-main.kicad_sch', 'sub/_autosave-child.kicad_sch',
                         'sub/_AUTOSAVE-other.kicad_sch'):
                (base / name).write_text('invalid autosave content', encoding='utf-8')
            result = discover(base)
            self.assertEqual(len(result.sheets), 1)
            self.assertEqual([p.name for p in result.roots], ['main.kicad_sch'])
            self.assertEqual(result.diagnostics, [])

    def test_nested_multiple_roots_and_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'sub').mkdir()
            (base / 'main.kicad_sch').write_text(schematic('sub/child.kicad_sch', 'sub/child.kicad_sch'), encoding='utf-8')
            (base / 'sub/child.kicad_sch').write_text(schematic(), encoding='utf-8')
            (base / 'other.kicad_sch').write_text(schematic(), encoding='utf-8')
            result = discover(base)
            self.assertEqual(len(result.sheets), 3)
            self.assertEqual({p.name for p in result.roots}, {'main.kicad_sch', 'other.kicad_sch'})
            self.assertEqual(len(result.sheets[(base / 'main.kicad_sch').resolve()].refs), 2)

    def test_external_missing_removed_before_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'inside'
            base.mkdir()
            outside = Path(folder) / 'secret.kicad_sch'
            outside.write_text('not a valid schematic', encoding='utf-8')
            source = base / 'main.kicad_sch'
            original = schematic('../secret.kicad_sch', 'absent.kicad_sch')
            source.write_text(original, encoding='utf-8')

            def fake_run(arguments, **kwargs):
                staged = Path(arguments[-1])
                self.assertNotIn('(sheet ', staged.read_text(encoding='utf-8'))
                self.assertNotEqual(staged, source)
                output = Path(arguments[arguments.index('--output') + 1])
                output.write_text('<export><nets/></export>', encoding='utf-8')
                return subprocess.CompletedProcess(arguments, 0, '', '')

            with patch('kicad_import.subprocess.run', side_effect=fake_run) as run:
                result = import_folder(base, cli='fake-cli')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(result.diagnostics), 2)
            self.assertIn('フォルダー外', result.diagnostics[0])
            self.assertEqual(source.read_text(encoding='utf-8'), original)

    def test_cycle_even_without_root(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'a.kicad_sch').write_text(schematic('b.kicad_sch'), encoding='utf-8')
            (base / 'b.kicad_sch').write_text(schematic('a.kicad_sch'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '循環'):
                discover(base)

    def test_parser_quotes_and_invalid_input(self):
        text = schematic('with space (1).kicad_sch')
        self.assertEqual(parse_schematic(serialize(parse_schematic(text))), parse_schematic(text))
        for invalid in ('(kicad_sch', '(other)', ')', '(kicad_sch "broken)', '(kicad_sch) garbage'):
            with self.assertRaises(ValueError):
                parse_schematic(invalid)

    def test_xml_scopes_and_terminals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'net.xml'
            path.write_text('''<export><components><comp ref="J1"><sheetpath names="/child/"/></comp>
                <comp ref="J2"><sheetpath names="/"/></comp></components><nets>
                <net name="+24V"><node ref="J1" pin="1"/><node ref="J2" pin="2"/>
                <node ref="J2" pin="2"/></net></nets></export>''', encoding='utf-8')
            a = read_netlist(path, 'a', '/project/a')[0]
            b = read_netlist(path, 'a', '/different/a')[0]
            self.assertNotEqual(a.key, b.key)
            self.assertEqual(a.name, '+24V')
            self.assertEqual(len(a.terminals), 2)
            self.assertEqual(a.terminals[0].sheet, '/child/')
            self.assertEqual(a.terminals[0].device, 'J1')
            self.assertEqual(b.terminals[0].device, 'J1')

    def test_export_error_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'a.kicad_sch').write_text(schematic(), encoding='utf-8')
            with patch('kicad_import.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'error')):
                with self.assertRaises(ValueError):
                    import_folder(folder, cli='fake')

    def test_missing_pin_numbers_report_all_references(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.xml'
            path.write_text('''<export><nets><net name="A">
                <node ref="J1" pin="" pinfunction="COM"/>
                <node ref="J2" pinfunction="COM"/>
                <node ref="J3" pin="   "/>
                <node ref="J1" pin=""/>
                </net></nets></export>''', encoding='utf-8')
            with self.assertRaises(ValueError) as caught:
                read_netlist(path, 'main')
            self.assertIn('J1, J2, J3', str(caught.exception))

    def test_unconnected_library_pin_is_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.xml'
            path.write_text('''<export><components>
                <comp ref="U1"><libsource lib="L" part="P"/></comp>
                <comp ref="U2"><libsource lib="L" part="P"/></comp></components>
                <libparts><libpart lib="L" part="P"><pins>
                <pin num="1"/><pin num=""/></pins></libpart></libparts><nets/>
                </export>''', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'U1, U2'):
                read_netlist(path, 'main')

    def test_same_pinfunction_keeps_distinct_pin_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ok.xml'
            path.write_text('''<export><nets><net name="A">
                <node ref="J1" pin="1" pinfunction="COM"/>
                <node ref="J1" pin="2" pinfunction="COM"/>
                </net></nets></export>''', encoding='utf-8')
            terminals = read_netlist(path, 'main')[0].terminals
            self.assertEqual([t.pin for t in terminals], ['1', '2'])
            self.assertEqual([t.pinfunction for t in terminals], ['COM', 'COM'])
            self.assertNotEqual(terminals[0].label, terminals[1].label)


if __name__ == '__main__':
    unittest.main()
