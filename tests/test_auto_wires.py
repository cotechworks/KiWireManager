import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import tempfile
import unittest

from kicad_import import ImportedNet, Terminal, merge_imported_wires
from wire_model import Numbering, Wire, assign_numbers, export_csv, load_project, save_project


class AutoWireTests(unittest.TestCase):
    def test_chain_uses_import_order_and_retains_every_terminal(self):
        terminals = [Terminal('C', '3'), Terminal('A', '1'), Terminal('B', '2')]
        nets = [ImportedNet('N1', 'N1', 'root', terminals),
                ImportedNet('N2', 'N2', 'root', [Terminal('D', '1'), Terminal('E', '2')])]
        wires = merge_imported_wires([], nets)
        self.assertEqual([(w.source_device, w.target_device) for w in wires], [('C', 'A'), ('A', 'B'), ('D', 'E')])
        assign_numbers(wires)
        self.assertEqual([w.number for w in wires], ['001', '001', '002'])

    def test_single_and_zero_terminal_nets_remain_numberable_and_saved(self):
        nets = [ImportedNet('N1', 'one', 'root', [Terminal('A', '1')]),
                ImportedNet('N2', 'empty', 'root', [])]
        wires = merge_imported_wires([], nets)
        self.assertEqual(len(wires), 2)
        self.assertEqual(wires[0].source_device, 'A')
        self.assertEqual(wires[0].target_device, '')
        assign_numbers(wires)
        self.assertEqual([w.number for w in wires], ['001', '002'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, wires, Numbering())
            self.assertEqual(load_project(path)[0], wires)
            with self.assertRaises(ValueError):
                export_csv(Path(folder) / 'wires.csv', wires)

    def test_repeat_and_reversed_existing_wire_preserve_ids(self):
        a, b, c = Terminal('A', '1'), Terminal('B', '2'), Terminal('C', '3')
        net = ImportedNet('N', 'N', 'root', [a, b, c])
        old = Wire(source_device='B', source_terminal='2', target_device='A', target_terminal='1', net_name='N', number='007')
        original = [old]
        merged = merge_imported_wires(original, [net])
        self.assertEqual(len(original), 1)
        self.assertEqual(len(merged), 2)
        self.assertIs(merged[0], old)
        self.assertEqual(merged[0].number, '007')
        self.assertEqual(merge_imported_wires(merged, [net]), merged)

    def test_same_pinfunction_different_pins_are_connected(self):
        net = ImportedNet('N', 'N', 'root', [Terminal('A', '1', pinfunction='COM'), Terminal('A', '2', pinfunction='COM')])
        wire = merge_imported_wires([], [net])[0]
        self.assertEqual((wire.source_terminal, wire.target_terminal), ('1', '2'))


if __name__ == '__main__':
    unittest.main()
