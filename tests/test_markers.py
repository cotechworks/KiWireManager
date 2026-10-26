import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import unittest
from uuid import uuid4

import test_writeback
from kicad_import import children, parse_schematic, discover
from schematic_annotations import (MARKER_GROUP, marked_text_ids, unmanaged_marker_warnings,
                                   edit_texts, TextEdit)
from schematic_writeback import execute_writeback
from wire_model import TextAnnotation, Numbering
from wiring_types import WiringType, clear_excluded_numbers


class MarkerTests(unittest.TestCase):
    setUp = test_writeback.WritebackTests.setUp
    plan = test_writeback.WritebackTests.plan

    def test_creation_migration_and_repeat_preserve_group_uuid(self):
        legacy_id = '33333333-3333-4333-8333-333333333333'
        annotation = TextAnnotation(self.sheet.name, legacy_id, self.key, '001')
        plan = self.plan([annotation])
        self.assertEqual(plan.marker_additions, 1)
        execute_writeback(plan, validator=lambda p: None)
        root = self.imported.sheets[self.sheet].node
        self.assertEqual(marked_text_ids(root), {legacy_id})
        groups = children(root, 'group')
        self.assertEqual(len(groups), 1)
        before = self.sheet.read_bytes()
        repeated = self.plan(plan.annotations)
        self.assertEqual(repeated.marker_additions, 0)
        self.assertEqual(repeated.updates, {})
        self.assertEqual(self.sheet.read_bytes(), before)

    def test_detects_every_marked_text_without_json_and_blocks_duplicate_write(self):
        plan = self.plan()
        execute_writeback(plan, validator=lambda p: None)
        warnings = unmanaged_marker_warnings(self.imported, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn(plan.annotations[0].text_uuid, warnings[0])
        self.assertEqual(unmanaged_marker_warnings(self.imported, plan.annotations), [])
        from schematic_writeback import UnmanagedMarkedTexts
        with self.assertRaises(UnmanagedMarkedTexts):
            self.plan([])

    def test_exclusion_removes_text_and_marker_group(self):
        from schematic_writeback import prepare_writeback
        plan = self.plan()
        execute_writeback(plan, validator=lambda p: None)
        kind = WiringType().key
        settings = Numbering(wire_types={kind: False}, net_wire_types={self.key: [kind]})
        clear_excluded_numbers(self.wires, settings)
        deletion = prepare_writeback(self.imported, self.wires, settings, plan.annotations, self.project)
        execute_writeback(deletion, validator=lambda p: None)
        self.assertEqual(children(self.imported.sheets[self.sheet].node, 'group'), [])
        self.assertEqual(len(children(self.imported.sheets[self.sheet].node, 'text')), 1)

    def test_confirmed_orphan_deletion_recreates_current_number_without_duplicates(self):
        initial = self.plan()
        execute_writeback(initial, validator=lambda p: None)
        old_id = initial.annotations[0].text_uuid
        before = self.sheet.read_bytes()
        plan = self.plan([], delete_unmanaged=True)
        self.assertEqual(sum(e.number is None for e in plan.edits), 1)
        backup = execute_writeback(plan, validator=lambda p: None)
        self.assertEqual((backup / self.sheet.name).read_bytes(), before)
        root = self.imported.sheets[self.sheet].node
        self.assertNotIn(old_id, marked_text_ids(root))
        self.assertEqual(marked_text_ids(root), {plan.annotations[0].text_uuid})
        self.assertEqual(len(children(root, 'text')), 2)  # Original user text plus one numbered text.
        self.assertEqual(self.plan(plan.annotations).updates, {})

    def test_confirmed_orphan_only_cleanup_without_wires(self):
        from schematic_writeback import prepare_writeback
        initial = self.plan()
        execute_writeback(initial, validator=lambda p: None)
        plan = prepare_writeback(self.imported, [], Numbering(), [], self.project, delete_unmanaged=True)
        self.assertEqual(len(plan.edits), 1)
        execute_writeback(plan, validator=lambda p: None)
        root = self.imported.sheets[self.sheet].node
        self.assertEqual(children(root, 'group'), [])
        self.assertEqual(len(children(root, 'text')), 1)

    def test_orphan_deletion_is_restored_when_project_write_fails(self):
        from unittest.mock import patch
        from schematic_writeback import atomic_write
        initial = self.plan()
        execute_writeback(initial, validator=lambda p: None)
        plan = self.plan([], delete_unmanaged=True)
        before = {p: p.read_bytes() for p in plan.originals}
        failed = False
        def write(path, content):
            nonlocal failed
            if path == self.project and not failed:
                failed = True
                raise PermissionError('simulated failure')
            atomic_write(path, content)
        with patch('schematic_writeback.atomic_write', side_effect=write):
            with self.assertRaisesRegex(ValueError, '復元しました'):
                execute_writeback(plan, validator=lambda p: None)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_recreation_cleans_stale_group_and_marks_new_uuid(self):
        plan = self.plan()
        execute_writeback(plan, validator=lambda p: None)
        original = self.sheet.read_bytes()
        annotation = plan.annotations[0]
        # Remove the graphical text only, emulating a deleted member.
        from schematic_annotations import top_level_spans, uid
        text = original.decode('utf-8')
        for start, end in reversed(top_level_spans(text)):
            node = parse_schematic('(kicad_sch ' + text[start:end] + ')')[1]
            if node[0] == 'text' and uid(node) == annotation.text_uuid:
                text = text[:start] + text[end:]
        self.sheet.write_text(text, encoding='utf-8')
        nets = self.imported.nets
        self.imported = discover(self.base)
        self.imported.nets = nets
        recreated = self.plan(plan.annotations, recreate_missing=True)
        execute_writeback(recreated, validator=lambda p: None)
        self.assertEqual(len(children(self.imported.sheets[self.sheet].node, 'group')), 1)
        self.assertEqual(marked_text_ids(self.imported.sheets[self.sheet].node), {recreated.annotations[0].text_uuid})
        self.assertNotEqual(annotation.text_uuid, recreated.annotations[0].text_uuid)

    def test_ordinary_groups_are_preserved_and_conflicting_members_are_refused(self):
        raw = self.sheet.read_bytes()
        group = f'(group "user" (uuid "{uuid4()}") (members "33333333-3333-4333-8333-333333333333"))'
        raw = raw[:raw.rfind(b')')] + group.encode() + b')'
        edit = TextEdit(self.sheet, self.key, '002', 'new-text-id', None, (20, 20))
        result = edit_texts(raw, [edit])
        self.assertIn(group.encode(), result)
        edit = TextEdit(self.sheet, self.key, '002', '33333333-3333-4333-8333-333333333333', '001')
        with self.assertRaisesRegex(ValueError, 'グループ解除'):
            edit_texts(raw, [edit])

    def test_shared_marker_group_retains_other_text_when_member_removed(self):
        a, b = str(uuid4()), str(uuid4())
        raw = f'''(kicad_sch (text "001" (uuid "{a}")) (text "002" (uuid "{b}"))
            (group "{MARKER_GROUP}" (uuid "{uuid4()}") (members "{a}" "{b}")))'''.encode()
        result = edit_texts(raw, [TextEdit(self.sheet, 'A', None, a, '001')])
        self.assertEqual(marked_text_ids(parse_schematic(result.decode())), {b})

    def test_invalid_marker_members_do_not_become_wire_numbers(self):
        identifier = str(uuid4())
        node = parse_schematic(f'''(kicad_sch (wire (uuid "{identifier}"))
            (group "{MARKER_GROUP}" (uuid "{uuid4()}") (members "{identifier}")))''')
        with self.assertRaises(ValueError):
            marked_text_ids(node)

    def test_nested_marker_group_deletion_does_not_leave_dangling_parent(self):
        identifier, group_id = str(uuid4()), str(uuid4())
        raw = f'''(kicad_sch (text "001" (uuid "{identifier}"))
            (group "{MARKER_GROUP}" (uuid "{group_id}") (members "{identifier}"))
            (group "user" (uuid "{uuid4()}") (members "{group_id}")))'''.encode()
        with self.assertRaisesRegex(ValueError, 'グループ解除'):
            edit_texts(raw, [TextEdit(self.sheet, 'A', None, identifier, '001')])


if __name__ == '__main__':
    unittest.main()
