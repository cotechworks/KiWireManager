"""Real Tk smoke test; requires a desktop display. Run: python tests/gui_smoke.py"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from kiwiremanager import Application


root = tk.Tk()
root.withdraw()
try:
    app = Application(root)
    for key, value in {'source_device': 'PLC1', 'source_terminal': 'X0',
                       'target_device': 'TB1', 'target_terminal': '1'}.items():
        app.inputs[key].set(value)
    app.add()
    app.number()
    root.update()
    assert app.wires[0].number == '001'
    identity = app.wires[0].wire_id
    app.table.selection_set(identity)
    app.select()
    app.inputs['target_terminal'].set('2')
    app.update()
    assert app.wires[0].target_terminal == '2'
    assert app.wires[0].wire_id == identity
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / 'project.json')
        with patch('kiwiremanager.filedialog.asksaveasfilename', return_value=path):
            assert app.save()
        app.new()
        assert not app.wires
        with patch('kiwiremanager.filedialog.askopenfilename', return_value=path):
            app.open()
        assert app.wires[0].number == '001'
        assert app.wires[0].target_terminal == '2'
        csv_path = str(Path(folder) / 'wires.csv')
        with patch('kiwiremanager.filedialog.asksaveasfilename', return_value=csv_path):
            app.export()
        assert Path(csv_path).exists()
        app.changed()
        with patch('kiwiremanager.messagebox.askyesnocancel', return_value=None):
            app.new()
        assert len(app.wires) == 1
    print('GUI smoke: PASS (add, number, edit, save, new, open, CSV, cancel)')
finally:
    root.destroy()
