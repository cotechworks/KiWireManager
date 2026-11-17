"""Automated T-079 case 3: mixed stroke types and unknown/manual nets."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import csv
import tempfile
import unittest
from uuid import uuid4
from kicad_import import discover, ImportedNet, Terminal, merge_imported_wires
from wiring_types import WiringType, collect_wiring_types
from wire_model import Numbering, Wire, assign_numbers, export_csv
from test_writeback import schematic


class CsvWireTypesTests(unittest.TestCase):
    def test_mixed_types_from_schematic_to_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'main.kicad_sch'
            original = schematic(str(uuid4())).replace(
                '(wire (pts (xy 10 10) (xy 30 10)))',
                '(wire (pts (xy 10 10) (xy 20 10)) (stroke (type solid)))'
                '(wire (pts (xy 20 10) (xy 30 10)) (stroke (type dash)))')
            path.write_text(original, encoding='utf-8')
            imported = discover(folder)
            imported.nets = [ImportedNet('TEST_MIX', 'TEST_MIX', path.name,
                              [Terminal('J1','1','/'), Terminal('J2','1','/')])]
            types, mapping, _ = collect_wiring_types(imported)
            solid, dash = WiringType('solid').key, WiringType('dash').key
            self.assertEqual(set(mapping['TEST_MIX']), {solid, dash})
            wires = merge_imported_wires([], imported.nets)
            # Another physical wire belongs to the same electrical net.
            wires.append(Wire('J2','1','J3','1',net_name='TEST_MIX'))
            settings = Numbering(wire_types=dict.fromkeys(types, True), net_wire_types=mapping)
            output = Path(folder) / 'out.csv'
            for solid_on, dash_on in ((True,True), (False,True), (True,False), (False,False), (True,True)):
                with self.subTest(solid=solid_on, dash=dash_on):
                    settings.wire_types.update({solid:solid_on, dash:dash_on})
                    assign_numbers(wires, settings)
                    export_csv(output, wires, settings)
                    with output.open(encoding='utf-8-sig',newline='') as stream:
                        rows = list(csv.DictReader(stream))
                    expected = len(wires) if solid_on or dash_on else 0
                    self.assertEqual(len(rows), expected)
                    self.assertEqual({row['電線ID'] for row in rows},
                                     {w.wire_id for w in wires} if expected else set())
                    self.assertTrue(all(w.number == ('001' if expected else '') for w in wires))
                    self.assertEqual(len(wires), 2)
            self.assertEqual(path.read_text(encoding='utf-8'), original)

    def test_unknown_and_manual_remain_in_csv_when_all_types_off(self):
        solid, dash = WiringType('solid').key, WiringType('dash').key
        settings = Numbering(wire_types={solid:False,dash:False},
                             net_wire_types={'OFF':[solid,dash], 'UNKNOWN':[]})
        wires = [Wire('A','1','B','1',net_name=net) for net in ('OFF','UNKNOWN','TEST_MANUAL')]
        assign_numbers(wires,settings)
        self.assertEqual([w.number for w in wires], ['', '001', '002'])
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'out.csv'
            export_csv(output,wires,settings)
            with output.open(encoding='utf-8-sig',newline='') as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual([row['ネット名'] for row in rows],['UNKNOWN','TEST_MANUAL'])
            self.assertEqual([row['線番'] for row in rows],['001','002'])
            self.assertEqual(len(wires),3)
