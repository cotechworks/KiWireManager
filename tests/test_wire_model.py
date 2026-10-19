import csv
import json
import tempfile
import unittest
from pathlib import Path

from wire_model import Numbering, Wire, assign_numbers, export_csv, issues, load_project, save_project


def wire(number=''):
    return Wire('PLC1', 'X0', 'TB1', '1', number)


class WireModelTests(unittest.TestCase):
    def test_preserve_skip_and_repeat(self):
        wires = [wire(), wire('W002'), wire('custom'), wire()]
        settings = Numbering('W', 1, 3)
        self.assertEqual(assign_numbers(wires, settings), 2)
        self.assertEqual([w.number for w in wires], ['W001', 'W002', 'custom', 'W003'])
        self.assertEqual(assign_numbers(wires, settings), 0)
        wires.append(wire())
        assign_numbers(wires, settings)
        self.assertEqual(wires[-1].number, 'W004')

    def test_invalid_wires_do_not_partially_number(self):
        for invalid in ([wire(), wire('001'), wire('001')], [wire(), Wire()]):
            with self.assertRaises(ValueError):
                assign_numbers(invalid, Numbering())
            self.assertEqual(invalid[0].number, '')

    def test_number_boundaries(self):
        wires = [wire(), wire()]
        assign_numbers(wires, Numbering('', 99, 2))
        self.assertEqual([w.number for w in wires], ['99', '100'])
        wires = [wire()]
        assign_numbers(wires, Numbering('', 0, 1))
        self.assertEqual(wires[0].number, '0')
        for settings in (Numbering(start=-1), Numbering(digits=0), Numbering(digits=13), Numbering(start=True)):
            with self.assertRaises(ValueError):
                assign_numbers([wire()], settings)

    def test_validation(self):
        self.assertEqual(issues([wire()]), ['1行目: 未採番です。'])
        self.assertEqual(len(issues([wire('1'), wire('1')])), 2)
        self.assertTrue(issues([Wire(source_device=' ')]))

    def test_roundtrip_and_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            wires = [wire('001')]
            wires[0].source_device = '端子台,試験'
            settings = Numbering('W', 10, 4)
            save_project(path, wires, settings)
            loaded, loaded_settings = load_project(path)
            self.assertEqual(loaded, wires)
            self.assertEqual(loaded_settings, settings)
            save_project(path, loaded, settings)
            csv_path = Path(folder) / 'wires.csv'
            export_csv(csv_path, wires)
            self.assertTrue(csv_path.read_bytes().startswith(b'\xef\xbb\xbf'))
            with csv_path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[1][1:4], ['001', '端子台,試験', 'X0'])

    def test_reject_bad_project(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, [wire()], Numbering())
            valid = json.loads(path.read_text(encoding='utf-8'))
            cases = [[], {'version': 2}, {**valid, 'wires': [valid['wires'][0]] * 2},
                     {**valid, 'wires': [{}]}, {**valid, 'numbering': {'digits': '3'}}]
            for data in cases:
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_project(path)

    def test_invalid_export_preserves_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wires.csv'
            path.write_text('original', encoding='utf-8')
            with self.assertRaises(ValueError):
                export_csv(path, [wire()])
            self.assertEqual(path.read_text(encoding='utf-8'), 'original')


if __name__ == '__main__':
    unittest.main()
