import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wire_model import Wire, Numbering, set_net_number, assign_numbers, save_project, load_project, export_csv, TextAnnotation
import test_writeback as fixtures
from schematic_writeback import execute_writeback

class ManualTests(unittest.TestCase):
    def test_text_shared_persistence_and_auto(self):
        wires=[Wire('A','1','B','1',net_name=n) for n in ('A','A','B')];settings=Numbering()
        set_net_number(wires,settings,'A','P24');assign_numbers(wires,settings)
        self.assertEqual([w.number for w in wires],['P24','P24','001'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'p.json';save_project(path,wires,settings)
            loaded,config,_=load_project(path);assign_numbers(loaded,config)
            self.assertEqual(config.manual_numbers,{'A':'P24'})
            csv=Path(folder)/'p.csv';export_csv(csv,loaded,config)
            self.assertIn('P24',csv.read_text(encoding='utf-8-sig'))
        set_net_number(wires,settings,'A','');assign_numbers(wires,settings)
        self.assertEqual([w.number for w in wires],['001','001','002'])

    def test_duplicate_and_invalid_atomic(self):
        wires=[Wire(net_name='A',number='P24'),Wire(net_name='B',number='001')];settings=Numbering()
        for net,value in [('B','P24'),('A','x\ny'),('unknown','Q')]:
            with self.assertRaises(ValueError):set_net_number(wires,settings,net,value)
        self.assertEqual([w.number for w in wires],['P24','001'])
        self.assertEqual(settings.manual_numbers,{})
        set_net_number(wires,settings,'A','002');assign_numbers(wires,settings)
        self.assertEqual([w.number for w in wires],['002','001'])

class ManualWritebackTests(unittest.TestCase):
    setUp=fixtures.WritebackTests.setUp
    plan=fixtures.WritebackTests.plan
    def test_text_writeback(self):
        self.wires[0].number='P24'
        plan=self.plan();execute_writeback(plan,validator=lambda p:None)
        self.assertIn(b'(text "P24"',self.sheet.read_bytes())
        self.assertEqual(load_project(self.project)[2][0].last_written_number,'P24')
        self.assertEqual(self.plan(plan.annotations).updates,{})
