import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import tempfile
import unittest
from uuid import uuid4

from kicad_import import discover, ImportedNet, Terminal, parse_schematic
from wiring_types import WiringType, read_wiring_type, collect_wiring_types
from test_writeback import schematic
from wire_model import Numbering, Wire, load_project, save_project, assign_numbers, issues, export_csv
from wiring_types import excluded_nets, clear_excluded_numbers


class WiringTypeTests(unittest.TestCase):
    def test_all_types_must_be_off_and_unknown_stays_eligible(self):
        a, b = WiringType().key, WiringType('dash').key
        settings = Numbering(wire_types={a: False, b: True},
                             net_wire_types={'mixed': [a, b], 'off': [a], 'unknown': []})
        self.assertEqual(excluded_nets(settings), {'off'})
        wires = [Wire('A', '1', 'B', '1', '009', net_name=net)
                 for net in ('mixed', 'off', 'unknown', 'manual', 'mixed')]
        assign_numbers(wires, settings)
        self.assertEqual([w.number for w in wires], ['001', '', '002', '003', '001'])
        self.assertEqual(issues(wires, settings=settings), [])
        settings.wire_types[b] = False
        self.assertEqual(clear_excluded_numbers(wires, settings), 2)
        assign_numbers(wires, settings)
        self.assertEqual([w.number for w in wires], ['', '', '001', '002', ''])
        settings.wire_types[a] = True
        assign_numbers(wires, settings)
        self.assertEqual([w.number for w in wires], ['001', '002', '003', '004', '001'])

    def test_excluded_nets_do_not_consume_999_limit_and_failure_is_atomic(self):
        kind = WiringType().key
        wires = [Wire(net_name=f'N{i}', number='old') for i in range(1001)]
        settings = Numbering(wire_types={kind: False}, net_wire_types={'N0': [kind]})
        with self.assertRaises(ValueError):
            assign_numbers(wires, settings)
        self.assertTrue(all(w.number == 'old' for w in wires))
        settings.net_wire_types['N1'] = [kind]
        assign_numbers(wires, settings)
        self.assertEqual([w.number for w in wires[:3]], ['', '', '001'])
        self.assertEqual(wires[-1].number, '999')

    def test_csv_retains_excluded_rows_without_number_and_checks_endpoints(self):
        import csv
        kind = WiringType().key
        settings = Numbering(wire_types={kind: False}, net_wire_types={'N': [kind]})
        wire = Wire('J1', '1', 'J2', '2', net_name='N')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wires.csv'
            export_csv(path, [wire], settings)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(list(csv.reader(stream))[1][1:3], ['', 'N'])
            wire.number = '001'
            self.assertTrue(issues([wire], settings=settings))
            wire.number, wire.target_terminal = '', ''
            self.assertTrue(issues([wire], settings=settings))

    def test_settings_roundtrip_and_legacy_defaults(self):
        import json
        kind = WiringType().key
        settings = Numbering(wire_types={kind: False}, net_wire_types={'N': [kind]})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, [], settings)
            self.assertEqual(load_project(path)[1], settings)
            data = json.loads(path.read_text(encoding='utf-8'))
            del data['numbering']['wire_types']
            del data['numbering']['net_wire_types']
            path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(load_project(path)[1], Numbering())

    def test_invalid_settings_do_not_replace_saved_project(self):
        kind = WiringType().key
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, [], Numbering())
            before = path.read_bytes()
            for settings in (Numbering(wire_types={kind: 0}), Numbering(wire_types={'bad': True}),
                             Numbering(net_wire_types={'N': [kind]}),
                             Numbering(wire_types={kind: True}, net_wire_types={'N': [kind, kind]})):
                with self.assertRaises(ValueError):
                    save_project(path, [], settings)
                self.assertEqual(path.read_bytes(), before)

    def test_defaults_and_equivalent_decimal_values(self):
        default = read_wiring_type(parse_schematic('(kicad_sch (wire))')[1])
        explicit = read_wiring_type(parse_schematic('''(kicad_sch
            (wire (stroke (width 0.000) (type default) (color 0 0.0 0 0))))''')[1])
        self.assertEqual(default, explicit)
        self.assertEqual(default, WiringType())
        custom = read_wiring_type(parse_schematic('''(kicad_sch
            (wire (stroke (width 0.2500) (type dash) (color 255 0 12 1.0))))''')[1])
        self.assertEqual(custom, WiringType('dash', '0.25', ('255', '0', '12', '1')))

    def test_each_property_distinguishes_types(self):
        types = [WiringType(), WiringType('solid'), WiringType(width='0.25'),
                 WiringType(color=('255', '0', '0', '1'))]
        self.assertEqual(len({t.key for t in types}), 4)

    def test_mixed_net_and_unresolved_wire_properties(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'main.kicad_sch'
            text = schematic(str(uuid4())).replace('(wire (pts (xy 10 10) (xy 30 10)))', '''
                (wire (pts (xy 10 10) (xy 20 10)))
                (wire (pts (xy 20 10) (xy 30 10)) (stroke (width 0.25) (type dash) (color 255 0 0 1)))
                (wire (pts (xy 50 50) (xy 60 50)) (stroke (width 0.5) (type dot)))''')
            path.write_text(text, encoding='utf-8')
            result = discover(folder)
            result.nets = [ImportedNet('N', 'N', 'main.kicad_sch',
                          [Terminal('J1', '1', '/'), Terminal('J2', '1', '/')])]
            types, mapping, warnings = collect_wiring_types(result)
            self.assertEqual(len(types), 3)
            self.assertEqual(set(mapping['N']), {WiringType().key,
                WiringType('dash', '0.25', ('255', '0', '0', '1')).key})
            self.assertEqual(path.read_text(encoding='utf-8'), text)

    def test_hierarchy_unions_types_across_sheets(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            child = base / 'child.kicad_sch'
            text = schematic(str(uuid4())).replace('(wire (pts (xy 10 10) (xy 30 10)))',
                '(wire (pts (xy 10 10) (xy 30 10)) (stroke (width 0.25) (type dash)))')
            child.write_text(text[:text.rfind(')')] + '(hierarchical_label "IN" (at 10 10 0)))', encoding='utf-8')
            main = base / 'main.kicad_sch'
            main.write_text(f'''(kicad_sch (uuid "{uuid4()}")
                (sheet (uuid "{uuid4()}") (property "Sheetname" "child")
                (property "Sheetfile" "child.kicad_sch") (pin "IN" input (at 10 10 0)))
                (wire (pts (xy 10 10) (xy 40 10))))''', encoding='utf-8')
            result = discover(folder)
            result.nets = [ImportedNet('N', 'N', main.name,
                [Terminal('J1', '1', '/child/'), Terminal('J2', '1', '/child/')])]
            types, mapping, _ = collect_wiring_types(result)
            self.assertEqual(set(mapping['N']), {WiringType().key, WiringType('dash', '0.25').key})
            self.assertEqual(set(types), set(mapping['N']))

    def test_crossing_without_junction_keeps_types_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'main.kicad_sch'
            text = schematic(str(uuid4()))
            text = text[:text.rfind(')')] + '''
                (symbol (lib_id "L:C") (at 20 0 0) (unit 1) (property "Reference" "J3"))
                (symbol (lib_id "L:C") (at 20 20 0) (unit 1) (property "Reference" "J4"))
                (wire (pts (xy 20 0) (xy 20 20)) (stroke (type dash))))'''
            path.write_text(text, encoding='utf-8')
            result = discover(folder)
            result.nets = [ImportedNet('A', 'A', path.name, [Terminal('J1', '1', '/'), Terminal('J2', '1', '/')]),
                           ImportedNet('B', 'B', path.name, [Terminal('J3', '1', '/'), Terminal('J4', '1', '/')])]
            _, mapping, _ = collect_wiring_types(result)
            self.assertEqual(mapping, {'A': [WiringType().key], 'B': [WiringType('dash').key]})


if __name__ == '__main__':
    unittest.main()
