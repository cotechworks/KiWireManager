import json
import unittest
from unittest.mock import patch
import test_writeback as fixtures
from schematic_writeback import prepare_delete_all, execute_writeback
from schematic_annotations import marked_text_ids
from wire_model import Numbering, load_project
from kicad_import import children, discover

class DeleteAllTests(unittest.TestCase):
    setUp = fixtures.WritebackTests.setUp
    plan = fixtures.WritebackTests.plan

    def delete_plan(self, annotations):
        return prepare_delete_all(self.imported,self.wires,Numbering(),annotations,self.project)

    def test_managed_and_orphan_preserve_normal_and_numbers(self):
        created=self.plan()
        execute_writeback(created,validator=lambda p: None)
        before=self.sheet.read_bytes()
        self.wires[0].number=''  # Deletion does not require numbering.
        plan=self.delete_plan([])  # The marker identifies orphan texts.
        self.assertEqual(len(plan.edits),1)
        backup=execute_writeback(plan,validator=lambda p: None)
        self.assertEqual((backup/'main.kicad_sch').read_bytes(),before)
        texts=children(discover(self.base).sheets[self.sheet].node,'text')
        self.assertEqual(len(texts),1)  # Original, untracked 001 text survives.
        self.assertFalse(marked_text_ids(discover(self.base).sheets[self.sheet].node))
        self.assertEqual(load_project(self.project)[0][0].number,'')
        self.assertEqual(load_project(self.project)[2],[])
        self.assertEqual(self.delete_plan([]).updates,{})

    def test_json_identification_and_outside_annotation_retained(self):
        created=self.plan()
        execute_writeback(created,validator=lambda p: None)
        # UUID alone must identify a legacy text whose marker has disappeared.
        from schematic_annotations import MARKER_GROUP
        node=discover(self.base).sheets[self.sheet].node
        node[:]=[item for item in node if not(isinstance(item,list) and item and item[0]=='group')]
        from kicad_import import serialize
        self.sheet.write_text(serialize(node),encoding='utf-8')
        self.imported=discover(self.base)
        plan=self.delete_plan(created.annotations)
        self.assertEqual(len(plan.edits),1)
        self.assertEqual(plan.annotations,[])

    def test_change_detection(self):
        self.sheet.write_bytes(self.sheet.read_bytes()+b' ')
        with self.assertRaises(ValueError): self.delete_plan([])

    def test_failure_restores_files(self):
        created=self.plan()
        execute_writeback(created,validator=lambda p: None)
        original=self.sheet.read_bytes()
        project=self.project.read_bytes()
        plan=self.delete_plan(created.annotations)
        import schematic_writeback as writer
        original_write=writer.atomic_write
        def fail(path,content):
            if path==self.project and content==plan.updates[self.project]:
                raise OSError('injected')
            return original_write(path,content)
        with patch.object(writer,'atomic_write',side_effect=fail):
            with self.assertRaises(ValueError): execute_writeback(plan,validator=lambda p:None)
        self.assertEqual(self.sheet.read_bytes(),original)
        self.assertEqual(self.project.read_bytes(),project)
