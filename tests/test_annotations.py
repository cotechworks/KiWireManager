import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from wire_model import Numbering, TextAnnotation, Wire, assign_numbers, load_project, save_project


class AnnotationTests(unittest.TestCase):
    def annotation(self):
        return TextAnnotation('power.kicad_sch', str(uuid4()), 'root::+24V', '001')

    def test_multiple_locations_and_last_written_number_roundtrip(self):
        annotations = [self.annotation(), self.annotation()]
        annotations[1].sheet = 'child.kicad_sch'
        wire = Wire(net_name='root::+24V', number='009')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, [wire], Numbering(), annotations)
            wires, settings, restored = load_project(path)
            self.assertEqual(restored, annotations)
            assign_numbers(wires)
            save_project(path, wires, settings, restored)
            self.assertEqual(load_project(path)[2], annotations)
            self.assertEqual(restored[0].last_written_number, '001')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['version'], 3)

    def test_version_two_migration_preserves_wire_id_and_number(self):
        wire = Wire(number='123', net_name='A')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.json'
            path.write_text(json.dumps({'version': 2, 'numbering': asdict(Numbering()), 'wires': [asdict(wire)]}), encoding='utf-8')
            wires, settings, annotations = load_project(path)
            self.assertEqual(wires, [wire])
            self.assertEqual(annotations, [])
            save_project(path, wires, settings, annotations)
            self.assertEqual(load_project(path), (wires, settings, []))

    def test_invalid_annotation_does_not_overwrite_project(self):
        valid = self.annotation()
        invalid = [replace(valid, text_uuid='invalid'), replace(valid, sheet=''),
                   replace(valid, net_key=5), replace(valid, last_written_number='000')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, [], Numbering(), [valid])
            original = path.read_bytes()
            for annotation in invalid:
                with self.assertRaises(ValueError):
                    save_project(path, [], Numbering(), [annotation])
                self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError):
                save_project(path, [], Numbering(), [valid, valid])

    def test_reject_corrupt_version_three_annotations(self):
        valid = self.annotation()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'project.json'
            save_project(path, [], Numbering(), [valid])
            payload = json.loads(path.read_text(encoding='utf-8'))
            for data in (None, {}, [{}], [asdict(replace(valid, text_uuid='bad'))], [asdict(valid)] * 2):
                path.write_text(json.dumps({**payload, 'annotations': data}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_project(path)


if __name__ == '__main__':
    unittest.main()
