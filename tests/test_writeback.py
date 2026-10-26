import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from kicad_import import ImportedNet, Terminal, discover, children
from schematic_annotations import edit_texts, first, on_segment, pin_positions, placement_candidates, TextEdit
from schematic_writeback import (prepare_writeback, execute_writeback, recover_transaction,
                                 MissingAnnotations, RecoveryRequired, pending_transactions)
from wire_model import Numbering, Wire, TextAnnotation, load_project, save_project


def schematic(identifier):
    return f'''(kicad_sch (version 20250114) (uuid "{identifier}")
      (lib_symbols (symbol "L:C" (symbol "C_1_1"
        (pin passive line (at 0 0 0) (number "1")))))
      (symbol (lib_id "L:C") (at 10 10 0) (unit 1)
        (uuid "11111111-1111-4111-8111-111111111111") (property "Reference" "J1"))
      (symbol (lib_id "L:C") (at 30 10 0) (unit 1)
        (uuid "22222222-2222-4222-8222-222222222222") (property "Reference" "J2"))
      (wire (pts (xy 10 10) (xy 30 10)))
      (text "001" (at 5 5 0) (effects (font (size 1.27 1.27)))
        (uuid "33333333-3333-4333-8333-333333333333")))'''


class WritebackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.sheet = self.base / 'main.kicad_sch'
        self.sheet.write_text(schematic(str(uuid4())), encoding='utf-8')
        self.imported = discover(self.base)
        self.key = self.sheet.as_posix() + '::N'
        self.imported.nets = [ImportedNet(self.key, 'N', 'main.kicad_sch', [Terminal('J1', '1', '/'), Terminal('J2', '1', '/')])]
        self.wires = [Wire('J1', '1', 'J2', '1', '001', net_name=self.key)]
        self.project = self.base / 'project.json'
        save_project(self.project, self.wires, Numbering())

    def plan(self, annotations=(), **kwargs):
        return prepare_writeback(self.imported, self.wires, Numbering(), annotations, self.project, **kwargs)

    def test_create_backup_update_and_no_duplicate(self):
        original = self.sheet.read_bytes()
        plan = self.plan()
        self.assertEqual(len(plan.edits), 1)
        self.assertEqual(plan.edits[0].position, (20, 8.73))
        backup = execute_writeback(plan, validator=lambda p: None)
        self.assertEqual((backup / 'main.kicad_sch').read_bytes(), original)
        self.assertIn(b'(text "001" (at 5 5 0)', self.sheet.read_bytes())
        self.assertEqual(load_project(self.project)[2], plan.annotations)
        self.assertEqual(self.plan(plan.annotations).updates, {})
        self.assertEqual(len(discover(self.base).sheets), 1)

    def test_missing_obsolete_net_does_not_block_recreation_of_current_net(self):
        stale_key = self.key + '-obsolete'
        annotation = TextAnnotation(self.sheet.name, str(uuid4()), self.key, '001')
        stale = TextAnnotation(self.sheet.name, str(uuid4()), stale_key, '002')
        self.wires.append(Wire(number='002', net_name=stale_key))
        with self.assertRaises(MissingAnnotations) as error:
            self.plan([stale, annotation])
        self.assertEqual(error.exception.identifiers, [f'{self.sheet.name}: {annotation.text_uuid}'])
        plan = self.plan([stale, annotation], recreate_missing=True)
        self.assertEqual(len(plan.edits), 1)
        self.assertEqual(plan.edits[0].net_key, self.key)
        self.assertIn(stale, plan.annotations)
        self.assertTrue(any('現在の回路図にネットがありません' in w for w in plan.warnings))
        execute_writeback(plan, validator=lambda p: None)
        repeated = self.plan(plan.annotations)
        self.assertEqual(repeated.updates, {})

    def test_missing_text_without_geometry_is_retained_as_warning(self):
        annotation = TextAnnotation(self.sheet.name, str(uuid4()), self.key, '001')
        with patch('schematic_writeback.placement_candidates', return_value=({}, [])):
            for recreate in (False, True):
                plan = self.plan([annotation], recreate_missing=recreate)
                self.assertEqual(plan.edits, [])
                self.assertEqual(plan.annotations, [annotation])
                self.assertTrue(any('配線の配置位置を特定できません' in w for w in plan.warnings))

    def test_update_preserves_position_and_font(self):
        first_plan = self.plan()
        execute_writeback(first_plan, validator=lambda p: None)
        text = self.sheet.read_text(encoding='utf-8')
        text = text.replace('(at 20.000000 8.730000 0)', '(at 77 88 90)').replace('(size 1.27 1.27)', '(size 2 2)')
        self.sheet.write_text(text, encoding='utf-8')
        nets = self.imported.nets
        self.imported = discover(self.base)
        self.imported.nets = nets
        self.wires[0].number = '002'
        plan = self.plan(first_plan.annotations)
        execute_writeback(plan, validator=lambda p: None)
        updated = self.sheet.read_text(encoding='utf-8')
        self.assertIn('(text "002" (at 77 88 90)', updated)
        self.assertIn('(size 2 2)', updated)

    def test_missing_uuid_requires_confirmation_and_stale_history_is_updated(self):
        annotation = TextAnnotation('main.kicad_sch', str(uuid4()), self.key, '001')
        with self.assertRaises(MissingAnnotations):
            self.plan([annotation])
        self.assertEqual(len(self.plan([annotation], recreate_missing=True).edits), 1)
        annotation.text_uuid = '33333333-3333-4333-8333-333333333333'
        annotation.last_written_number = '009'
        plan = self.plan([annotation])
        self.assertEqual(plan.edits[0].old_number, '001')
        self.assertEqual(plan.annotations[0].last_written_number, '001')
        self.assertNotIn(self.sheet, plan.updates)

    def test_app_number_overrides_edited_text_preserving_uuid_position_and_font(self):
        initial = self.plan()
        execute_writeback(initial, validator=lambda p: None)
        identifier = initial.annotations[0].text_uuid
        text = self.sheet.read_text(encoding='utf-8')
        text = text.replace('(text "001" (at 20.000000 8.730000 0)',
                            '(text "HAND" (at 77 88 90)')
        text = text.replace('(size 1.27 1.27)', '(size 2 2)')
        self.sheet.write_text(text, encoding='utf-8')
        nets = self.imported.nets
        self.imported = discover(self.base)
        self.imported.nets = nets
        self.wires[0].number = '007'
        plan = self.plan(initial.annotations)
        self.assertEqual(plan.edits[0].old_number, 'HAND')
        backup = execute_writeback(plan, validator=lambda p: None)
        self.assertIn(b'(text "HAND" (at 77 88 90)', (backup / self.sheet.name).read_bytes())
        updated = self.sheet.read_text(encoding='utf-8')
        self.assertIn('(text "007" (at 77 88 90)', updated)
        self.assertIn('(size 2 2)', updated)
        self.assertIn('(text "001" (at 5 5 0)', updated)
        self.assertEqual(plan.annotations[0].text_uuid, identifier)
        self.assertEqual(load_project(self.project)[2][0].last_written_number, '007')
        self.assertEqual(self.plan(plan.annotations).updates, {})

    def test_changed_source_and_project_refused(self):
        plan = self.plan()
        self.project.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            execute_writeback(plan, validator=lambda p: None)
        self.sheet.write_text(schematic(str(uuid4())), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '変更'):
            self.plan()

    def test_backup_failure_does_not_write_originals(self):
        plan = self.plan()
        before = {p: p.read_bytes() for p in plan.originals}
        (self.base / 'backup').write_text('not a directory')
        with self.assertRaises(OSError):
            execute_writeback(plan, validator=lambda p: None)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_json_failure_rolls_back_diagrams(self):
        from schematic_writeback import atomic_write
        plan = self.plan()
        before = {p: p.read_bytes() for p in plan.originals}
        failed = False
        def write(path, content):
            nonlocal failed
            if path == self.project and not failed:
                failed = True
                raise PermissionError('simulated project failure')
            atomic_write(path, content)
        with patch('schematic_writeback.atomic_write', side_effect=write):
            with self.assertRaisesRegex(ValueError, '復元しました'):
                execute_writeback(plan, validator=lambda p: None)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertEqual(pending_transactions(self.base), [])

    def test_unfinished_transaction_detected_and_recovered(self):
        plan = self.plan()
        before = {p: p.read_bytes() for p in plan.originals}
        backup = execute_writeback(plan, validator=lambda p: None)
        journal = backup / 'writeback.json'
        record = json.loads(journal.read_text(encoding='utf-8'))
        record['state'] = 'committing'
        journal.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(RecoveryRequired):
            self.plan(plan.annotations)
        recover_transaction(journal, self.base, self.project)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_recovery_does_not_overwrite_subsequent_edit(self):
        backup = execute_writeback(self.plan(), validator=lambda p: None)
        journal = backup / 'writeback.json'
        record = json.loads(journal.read_text(encoding='utf-8'))
        record['state'] = 'committing'
        journal.write_text(json.dumps(record), encoding='utf-8')
        self.sheet.write_text('user edit', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '編集された'):
            recover_transaction(journal, self.base, self.project)
        self.assertEqual(self.sheet.read_text(encoding='utf-8'), 'user edit')

    def test_rotation_mirror_and_non_connected_crossing(self):
        from kicad_import import parse_schematic
        library = {'L:C': parse_schematic('(kicad_sch (symbol "L:C" (symbol "C_1_1" (pin passive line (at 2 3 0) (number "1")))))')[1]}
        def pin(angle, mirror=''):
            symbol = parse_schematic(f'(kicad_sch (symbol (lib_id "L:C") (at 10 20 {angle}) (unit 1) {mirror}))')[1]
            return pin_positions(symbol, library)[0][1]
        self.assertEqual(pin(0), (12, 17))
        self.assertEqual(pin(90), (7, 18))
        self.assertEqual(pin(0, '(mirror y)'), (8, 17))
        self.assertEqual(pin(0, '(mirror x)'), (12, 23))
        self.assertTrue(on_segment((5, 0), (0, 0), (10, 0)))
        self.assertFalse(on_segment((5, 1), (0, 0), (10, 0)))

    def test_crossing_without_junction_stays_separate(self):
        source = self.sheet.read_text(encoding='utf-8')
        extra = '''(symbol (lib_id "L:C") (at 20 0 0) (unit 1) (property "Reference" "J3"))
          (symbol (lib_id "L:C") (at 20 20 0) (unit 1) (property "Reference" "J4"))
          (wire (pts (xy 20 0) (xy 20 20)))'''
        offset = source.rfind(')')
        self.sheet.write_text(source[:offset] + extra + source[offset:], encoding='utf-8')
        imported = discover(self.base)
        imported.nets = self.imported.nets + [ImportedNet('other', 'other', 'main.kicad_sch', [Terminal('J3', '1', '/'), Terminal('J4', '1', '/')])]
        positions, warnings = placement_candidates(imported)
        self.assertEqual(len(positions), 2)
        text = self.sheet.read_text(encoding='utf-8')
        self.sheet.write_text(text[:text.rfind(')')] + '(junction (at 20 10))' + ')', encoding='utf-8')
        connected = discover(self.base)
        connected.nets = imported.nets
        with self.assertRaisesRegex(ValueError, '競合'):
            placement_candidates(connected)

    def test_failed_recovery_can_be_retried(self):
        from schematic_writeback import atomic_write
        plan = self.plan()
        before = {p: p.read_bytes() for p in plan.originals}
        def write(path, content):
            if path == self.project:
                raise PermissionError('project remains locked')
            atomic_write(path, content)
        with patch('schematic_writeback.atomic_write', side_effect=write):
            with self.assertRaisesRegex(ValueError, '復元にも失敗'):
                execute_writeback(plan, validator=lambda p: None)
        pending = pending_transactions(self.base)
        self.assertEqual(len(pending), 1)
        recover_transaction(pending[0], self.base, self.project)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_validation_failure_does_not_create_backup_or_change_source(self):
        before = self.sheet.read_bytes()
        with self.assertRaises(ValueError):
            execute_writeback(self.plan(), validator=lambda p: (_ for _ in ()).throw(ValueError('invalid')))
        self.assertEqual(self.sheet.read_bytes(), before)
        self.assertFalse((self.base / 'backup').exists())

    def test_timestamp_collision_does_not_overwrite_backup(self):
        with patch('schematic_writeback.datetime') as clock:
            clock.now.return_value.astimezone.return_value.strftime.return_value = 'same_timestamp'
            plan = self.plan()
            first_backup = execute_writeback(plan, validator=lambda p: None)
            old_bytes = (first_backup / 'main.kicad_sch').read_bytes()
            self.wires[0].number = '002'
            second_backup = execute_writeback(self.plan(plan.annotations), validator=lambda p: None)
        self.assertNotEqual(first_backup, second_backup)
        self.assertEqual((first_backup / 'main.kicad_sch').read_bytes(), old_bytes)

    def test_hierarchical_pin_propagates_net_to_parent_wire(self):
        child = self.base / 'child.kicad_sch'
        original = schematic(str(uuid4()))
        child.write_text(original[:original.rfind(')')] + '(hierarchical_label "IN" (at 10 10 0))' + ')', encoding='utf-8')
        self.sheet.write_text(f'''(kicad_sch (uuid "{uuid4()}")
          (sheet (uuid "{uuid4()}") (property "Sheetname" "child")
            (property "Sheetfile" "child.kicad_sch") (pin "IN" input (at 10 10 0)))
          (wire (pts (xy 10 10) (xy 40 10))))''', encoding='utf-8')
        imported = discover(self.base)
        imported.nets = [ImportedNet(self.key, 'N', 'main.kicad_sch', [Terminal('J1', '1', '/child/'), Terminal('J2', '1', '/child/')])]
        positions, warnings = placement_candidates(imported)
        self.assertIn((self.sheet, self.key), positions)
        self.assertIn((child, self.key), positions)
