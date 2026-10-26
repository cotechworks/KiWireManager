"""Real Tk checkbox, reimport, save/reopen and new-project checks."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from kiwiremanager import Application
from kicad_import import discover, ImportedNet, Terminal
from wire_model import load_project
from wiring_types import WiringType
from test_writeback import schematic


root = tk.Tk()
root.withdraw()
try:
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        path = folder / 'main.kicad_sch'
        path.write_text(schematic(str(uuid4())), encoding='utf-8')
        result = discover(folder)
        result.nets = [ImportedNet('N', 'N', path.name, [Terminal('J1', '1', '/'), Terminal('J2', '1', '/')])]
        app = Application(root, settings_path=folder / 'settings.json')
        app.apply_import(result)
        kind = WiringType().key
        assert len(app.notebook.tabs()) == 4
        assert app.wiring_tab.variables[kind].get() is True
        app.number()
        assert app.wires[0].number == '001'
        app.wiring_tab.checks[kind].invoke()
        assert app.settings().wire_types[kind] is False
        assert app.wires[0].number == ''
        app.number()
        assert app.wires[0].number == ''
        with patch('kiwiremanager.messagebox.showinfo') as info:
            app.check()
        assert info.call_args.args[1] == '問題はありません。'
        app.apply_import(result)
        assert app.wiring_tab.variables[kind].get() is False
        app.path = folder / 'project.json'
        assert app.save()
        assert load_project(app.path)[1].wire_types[kind] is False
        with patch('kiwiremanager.filedialog.askopenfilename', return_value=str(app.path)):
            app.open()
        assert app.import_result is None
        assert app.wiring_tab.variables[kind].get() is False
        assert app.wires[0].number == ''
        app.wiring_tab.checks[kind].invoke()
        assert app.wires[0].number == '', 'enabling must wait for the numbering button'
        app.number()
        assert app.wires[0].number == '001'
        with patch('kiwiremanager.messagebox.askyesnocancel', return_value=False):
            app.new()
        assert not app.wiring_tab.variables
        assert not app.settings().wire_types
        assert app.notebook.tab(app.wiring_tab.frame, 'text') == '配線の種類'
        from schematic_annotations import MARKER_GROUP
        raw = path.read_text(encoding='utf-8')
        raw = raw[:raw.rfind(')')] + f'''(group "{MARKER_GROUP}" (uuid "{uuid4()}")
            (members "33333333-3333-4333-8333-333333333333")))'''
        path.write_text(raw, encoding='utf-8')
        marked_result = discover(folder)
        marked_result.nets = result.nets
        app.apply_import(marked_result)
        assert app.notebook.select() == str(app.import_tabs.diagnostic_frame)
        assert '33333333-3333-4333-8333-333333333333' in app.import_tabs.diagnostics.get('1.0', 'end')
        assert '1件' in app.status.get()
        print('PASS wiring types tab, default on, checkbox toggle, reimport retention, JSON restore, new reset')
finally:
    root.destroy()
