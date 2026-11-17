import sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kiwiremanager import Application
from marker_dialog import DECLINE_ALL
from wire_model import Wire

class DeclineAllTests(unittest.TestCase):
    def register(self, answers):
        app=SimpleNamespace(root=None,wires=[Wire(net_name='N',number='P24')],annotations=[])
        candidates=[('s.kicad_sch',f'12345678-1234-1234-1234-{i:012d}','P24') for i in range(3)]
        with patch('kiwiremanager.unregistered_marked_texts',return_value=candidates),patch('kiwiremanager.choose_net',side_effect=answers) as choose:
            changed=Application.register_copied_markers(app,None)
        return app,changed,choose.call_count

    def test_decline_all_stops_remaining_prompts(self):
        app,changed,calls=self.register([DECLINE_ALL])
        self.assertFalse(changed);self.assertEqual(calls,1);self.assertEqual(app.annotations,[])

    def test_previous_registration_is_retained(self):
        app,changed,calls=self.register(['N',DECLINE_ALL])
        self.assertTrue(changed);self.assertEqual(calls,2);self.assertEqual(len(app.annotations),1)

    def test_single_decline_continues(self):
        app,changed,calls=self.register([None,None,None])
        self.assertFalse(changed);self.assertEqual(calls,3)
