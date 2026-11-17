import unittest
from uuid import uuid4
import test_writeback as fixtures
from kicad_import import discover, children, value
from schematic_annotations import TextEdit, edit_texts, marked_text_ids, unregistered_marked_texts, MARKER_GROUP
from schematic_writeback import execute_writeback, prepare_delete_all
from wire_model import TextAnnotation, Numbering

class CopiedMarkerTests(unittest.TestCase):
    setUp=fixtures.WritebackTests.setUp
    plan=fixtures.WritebackTests.plan

    def copies(self):
        original=self.plan();execute_writeback(original,validator=lambda p:None)
        identifier=str(uuid4())
        content=edit_texts(self.sheet.read_bytes(),[TextEdit(self.sheet,self.key,'001',identifier,None,(25,8))])
        content=content.replace(MARKER_GROUP.encode(),(MARKER_GROUP+'21').encode())
        self.sheet.write_bytes(content)
        self.imported=discover(self.base)
        from kicad_import import ImportedNet,Terminal
        self.imported.nets=[ImportedNet(self.key,'N',self.sheet.name,[Terminal('J1','1','/'),Terminal('J2','1','/')])]
        return original.annotations,identifier

    def test_detect_register_update_multiple_and_delete(self):
        annotations,identifier=self.copies()
        candidates=unregistered_marked_texts(self.imported,annotations)
        self.assertEqual(candidates,[(self.sheet.name,identifier,'001')])
        annotations.append(TextAnnotation(self.sheet.name,identifier,self.key,'001'))
        self.wires[0].number='P24'
        plan=self.plan(annotations);self.assertEqual(len(plan.edits),2)
        execute_writeback(plan,validator=lambda p:None)
        self.assertEqual(len(marked_text_ids(self.imported.sheets[self.sheet].node)),2)
        self.assertEqual(self.plan(plan.annotations).updates,{})
        deletion=prepare_delete_all(self.imported,self.wires,Numbering(),plan.annotations,self.project)
        self.assertEqual(len(deletion.edits),2)
        execute_writeback(deletion,validator=lambda p:None)
        self.assertFalse(marked_text_ids(self.imported.sheets[self.sheet].node))
        self.assertEqual(len(children(self.imported.sheets[self.sheet].node,'text')),1)

    def test_declined_copy_not_changed(self):
        annotations,identifier=self.copies()
        before=self.sheet.read_bytes()
        from schematic_writeback import UnmanagedMarkedTexts
        with self.assertRaises(UnmanagedMarkedTexts):self.plan(annotations)
        self.assertEqual(self.sheet.read_bytes(),before)
