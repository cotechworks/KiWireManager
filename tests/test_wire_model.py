import csv
import json
import tempfile
import unittest
from pathlib import Path

from wire_model import Numbering, Wire, assign_numbers, export_csv, issues, load_project, save_project


def wire(number=''):
    return Wire('PLC1', 'X0', 'TB1', '1', number)


class WireModelTests(unittest.TestCase):
    def test_shared_net_and_idempotent(self):
        wires = [wire(), wire(), wire('legacy')]
        wires[0].net_name = wires[1].net_name = '101'
        self.assertEqual(assign_numbers(wires), 2)
        self.assertEqual([w.number for w in wires], ['001', '001', 'legacy'])
        self.assertEqual(assign_numbers(wires), 0)
        self.assertNotEqual(wires[0].wire_id, wires[1].wire_id)
        self.assertEqual(issues(wires[:2]), [])

    def test_invalid_endpoints_prevent_partial_update(self):
        wires = [wire(), Wire()]
        wires[0].net_name = '101'
        with self.assertRaises(ValueError):
            assign_numbers(wires)
        self.assertEqual(wires[0].number, '')

    def test_validation_and_rename(self):
        w = wire('old')
        self.assertTrue(issues([w]))
        w.net_name = 'new'
        self.assertTrue(issues([w]))
        assign_numbers([w])
        self.assertEqual(w.number, '001')
        self.assertEqual(issues([w]), [])

    def test_net_order_and_999_boundary(self):
        wires = [wire() for _ in range(1000)]
        for i, w in enumerate(wires):
            w.net_name = f'net{i}'
        with self.assertRaises(ValueError):
            assign_numbers(wires)
        self.assertTrue(all(not w.number for w in wires))
        assign_numbers(wires[:999])
        self.assertEqual(wires[0].number, '001')
        self.assertEqual(wires[998].number, '999')
        wires[999].net_name = wires[0].net_name
        assign_numbers(wires)
        self.assertEqual(wires[999].number, '001')

    def test_conflicting_and_invalid_numbers(self):
        a, b = wire('001'), wire('002')
        a.net_name = b.net_name = 'A'
        self.assertTrue(issues([a, b]))
        b.net_name, b.number = 'B', '001'
        self.assertTrue(issues([a, b]))
        assign_numbers([a, b])
        self.assertEqual([a.number, b.number], ['001', '002'])
        self.assertEqual(issues([a, b]), [])
        for number in ('000', '1000', '12', 'abc', '???'):
            a.number = number
            self.assertTrue(issues([a]))

    def test_legacy_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.json'
            w = wire('001')
            record = dict(w.__dict__)
            del record['net_name']
            path.write_text(json.dumps({'version': 1, 'numbering': {'prefix': 'W', 'start': 10, 'digits': 4}, 'wires': [record]}), encoding='utf-8')
            loaded, settings = load_project(path)
            self.assertEqual(loaded[0].wire_id, w.wire_id)
            self.assertEqual(loaded[0].number, '001')
            self.assertEqual(loaded[0].net_name, '')
            self.assertEqual(assign_numbers(loaded), 0)
            save_project(path, loaded, settings)
            self.assertEqual(load_project(path)[0], loaded)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['version'], 2)

    def test_roundtrip_and_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            wires = [wire('001')]
            wires[0].net_name = '001'
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
            self.assertEqual(rows[1][1:5], ['001', '001', '端子台,試験', 'X0'])

    def test_reject_bad_project(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, [wire()], Numbering())
            valid = json.loads(path.read_text(encoding='utf-8'))
            cases = [[], {'version': 99}, {**valid, 'wires': [valid['wires'][0]] * 2},
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
