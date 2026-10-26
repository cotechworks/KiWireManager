"""Exclude already annotated nets using the real backup/rollback pipeline."""
from unittest.mock import patch

from kicad_import import children, discover
from schematic_annotations import uid, value
from schematic_writeback import execute_writeback, prepare_writeback, atomic_write
from wire_model import Numbering, load_project
from wiring_types import WiringType, clear_excluded_numbers
import unittest
import test_writeback


class ExclusionWritebackTests(unittest.TestCase):
    setUp = test_writeback.WritebackTests.setUp
    plan = test_writeback.WritebackTests.plan
    def excluded_plan(self, annotations):
        kind = WiringType().key
        self.exclusion_settings = Numbering(wire_types={kind: False}, net_wire_types={self.key: [kind]})
        clear_excluded_numbers(self.wires, self.exclusion_settings)
        return prepare_writeback(self.imported, self.wires, self.exclusion_settings, annotations, self.project)

    def test_delete_managed_only_backup_json_and_idempotence(self):
        initial = self.plan()
        execute_writeback(initial, validator=lambda p: None)
        before = self.sheet.read_bytes()
        plan = self.excluded_plan(initial.annotations)
        self.assertEqual(len(plan.edits), 1)
        self.assertIsNone(plan.edits[0].number)
        self.assertEqual(plan.annotations, [])
        backup = execute_writeback(plan, validator=lambda p: None)
        self.assertEqual((backup / self.sheet.name).read_bytes(), before)
        texts = children(self.imported.sheets[self.sheet].node, 'text')
        self.assertEqual([(uid(n), value(n[1])) for n in texts],
                         [('33333333-3333-4333-8333-333333333333', '001')])
        wires, settings, annotations = load_project(self.project)
        self.assertEqual(wires[0].number, '')
        self.assertEqual(settings, self.exclusion_settings)
        self.assertEqual(annotations, [])
        self.assertEqual(self.excluded_plan([]).updates, {})
        # Enable again: numbering and placement return, with a new managed UUID.
        from wire_model import assign_numbers
        settings.wire_types[WiringType().key] = True
        assign_numbers(wires, settings)
        recreated = prepare_writeback(self.imported, wires, settings, [], self.project)
        self.assertIsNone(recreated.edits[0].old_number)
        self.assertNotEqual(recreated.edits[0].text_uuid, initial.annotations[0].text_uuid)

    def test_hand_changed_managed_text_blocks_deletion(self):
        initial = self.plan()
        execute_writeback(initial, validator=lambda p: None)
        text = self.sheet.read_text(encoding='utf-8').replace('(text "001" (at 20.', '(text "HAND" (at 20.')
        self.sheet.write_text(text, encoding='utf-8')
        nets = self.imported.nets
        self.imported = discover(self.base)
        self.imported.nets = nets
        before = self.sheet.read_bytes()
        with self.assertRaisesRegex(ValueError, '手動変更'):
            self.excluded_plan(initial.annotations)
        self.assertEqual(self.sheet.read_bytes(), before)

    def test_already_missing_excluded_text_is_not_recreated(self):
        from uuid import uuid4
        from wire_model import TextAnnotation
        annotation = TextAnnotation(self.sheet.name, str(uuid4()), self.key, '001')
        plan = self.excluded_plan([annotation])
        self.assertEqual(plan.edits, [])
        self.assertEqual(plan.annotations, [])
        self.assertNotIn(self.sheet, plan.updates)

    def test_failed_project_update_restores_deleted_text(self):
        initial = self.plan()
        execute_writeback(initial, validator=lambda p: None)
        plan = self.excluded_plan(initial.annotations)
        before = {p: p.read_bytes() for p in plan.originals}
        failed = False
        def write(path, content):
            nonlocal failed
            if path == self.project and not failed:
                failed = True
                raise PermissionError('simulated project failure during deletion')
            atomic_write(path, content)
        with patch('schematic_writeback.atomic_write', side_effect=write):
            with self.assertRaisesRegex(ValueError, '復元しました'):
                execute_writeback(plan, validator=lambda p: None)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
