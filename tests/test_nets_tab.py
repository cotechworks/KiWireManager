import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import unittest
from types import SimpleNamespace
from nets_tab import net_rows
from wire_model import Wire

class NetRowsTests(unittest.TestCase):
    def test_registered_group_and_distinct_roots(self):
        wires=[Wire('A','1','B','2','001',net_name='C:/a.kicad_sch::N'),Wire('B','2','C','3','001',net_name='C:/a.kicad_sch::N'),Wire(net_name='C:/b.kicad_sch::N')]
        rows=net_rows(wires)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0][1][:5],('N','001',2,3,'採番済み'))
        self.assertEqual(rows[1][1][4],'未採番あり')

    def test_import_only_and_unknown_names(self):
        imported=SimpleNamespace(nets=[SimpleNamespace(key='N',root='main',terminals=[1])])
        rows=net_rows([Wire()],imported)
        self.assertEqual(rows[0][1],('N','',0,1,'電線未登録','main'))
        self.assertEqual(net_rows([]),[])

    def test_conflicting_number(self):
        self.assertEqual(net_rows([Wire(net_name='N',number='001'),Wire(net_name='N',number='002')])[0][1][4],'線番不一致')

    def test_single_terminal_filter(self):
        imported=SimpleNamespace(nets=[SimpleNamespace(key='one',name='/Sheet/one',root='main',terminals=[1]),SimpleNamespace(key='zero',name='zero',root='main',terminals=[])])
        wires=[Wire('A','1',net_name='one'), Wire('B','1',net_name='manual')]
        self.assertEqual([key for key,values in net_rows(wires,imported,False)],['zero'])
        self.assertEqual(len(net_rows(wires,imported,True)),3)

    def test_display_only_and_electrical_identity(self):
        wires=[Wire('A','1','B','2',net_name='C:/root.kicad_sch::/SheetA/N'),Wire('B','2','C','3',net_name='C:/root.kicad_sch::/SheetA/N'),Wire('D','1','E','2',net_name='C:/root.kicad_sch::/SheetB/N')]
        original=[wire.net_name for wire in wires]
        rows=net_rows(wires,include_single_terminal=False)
        self.assertEqual(len(rows),2)
        self.assertEqual([values[0] for key,values in rows],['N','N'])
        self.assertEqual(rows[0][1][2],2)
        self.assertNotEqual(rows[0][0],rows[1][0])
        self.assertEqual(original,[wire.net_name for wire in wires])
