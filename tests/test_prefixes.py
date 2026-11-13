import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wire_model import Numbering, Wire, TextAnnotation, assign_numbers, save_project, load_project, export_csv, valid_number, validate_annotations
from wiring_types import WiringType

class PrefixTests(unittest.TestCase):
    def settings(self):
        a, b = WiringType().key, WiringType(style='dash').key
        return Numbering(wire_types={a: True, b: True}, net_wire_types={'N1': [a], 'N2': [b]}, wire_prefixes={a: 'P', b: ''}), a, b

    def test_numbering_and_persistence(self):
        settings, a, b = self.settings()
        wires = [Wire('A','1','B','2',net_name=n) for n in ('N1','N1','N2')]
        assign_numbers(wires, settings)
        self.assertEqual([w.number for w in wires], ['P001','P001','002'])
        annotation = TextAnnotation('main.kicad_sch','12345678-1234-1234-1234-123456789abc','N1','P001')
        validate_annotations([annotation])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'project.json'
            save_project(path,wires,settings,[annotation])
            restored, config, annotations = load_project(path)
            self.assertEqual(config.wire_prefixes, settings.wire_prefixes)
            self.assertEqual(annotations[0].last_written_number,'P001')
            csv = Path(folder)/'out.csv'
            export_csv(csv,restored,config)
            self.assertIn('P001',csv.read_text(encoding='utf-8-sig'))

    def test_conflict_is_atomic(self):
        settings,a,b = self.settings()
        settings.net_wire_types['N2']=[a,b]
        wires=[Wire(net_name='N1',number='007'),Wire(net_name='N2',number='008')]
        with self.assertRaisesRegex(ValueError,'N2'):
            assign_numbers(wires,settings)
        self.assertEqual([w.number for w in wires],['007','008'])
        settings.wire_prefixes[b]='P'
        assign_numbers(wires,settings)
        self.assertEqual([w.number for w in wires],['P001','P002'])

    def test_invalid_and_legacy(self):
        settings,a,b=self.settings()
        for prefix in ('AB','1','Ａ',' '):
            settings.wire_prefixes[a]=prefix
            with self.assertRaises(ValueError): settings.validate()
        for number in ('P000','AB001','P01','Ｐ001'):
            self.assertFalse(valid_number(number))
        self.assertTrue(valid_number('a999'))
        wires=[Wire(net_name='N')]
        assign_numbers(wires,Numbering())
        self.assertEqual(wires[0].number,'001')
