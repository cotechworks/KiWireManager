"""Integration check: python tests/import_smoke.py SCHEMATIC_FOLDER.

Needs KiCad 10 and a desktop. Reads originals; writes only temporary files.
"""
import hashlib
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from kicad_dialog import ImportDialog
from kiwiremanager import Application
from wire_model import load_project


def hashes(folder):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*.kicad_sch')}


folder = Path(sys.argv[1])
before = hashes(folder)
root = tk.Tk()
root.withdraw()
try:
    app = Application(root)
    with patch('kiwiremanager.filedialog.askdirectory', return_value=str(folder)), \
            patch('kiwiremanager.messagebox.showerror') as errors:
        app.import_kicad()
        deadline = time.monotonic() + 90
        dialog = None
        while time.monotonic() < deadline:
            root.update()
            dialogs = [w for w in root.winfo_children() if isinstance(w, ImportDialog)]
            if dialogs:
                dialog = dialogs[0]
                break
            if errors.called:
                raise AssertionError(ascii(errors.call_args))
            time.sleep(0.02)
        assert dialog is not None, 'import did not finish'
    result = dialog.result
    index = next(i for i, net in enumerate(result.nets) if len(net.terminals) >= 2)
    dialog.net_table.selection_set(str(index))
    dialog.select_net()
    dialog.source.current(0)
    dialog.target.current(1)
    dialog.add_selected()
    assert len(app.wires) == 1
    with patch('kiwiremanager.messagebox.showinfo'):
        dialog.add_selected()
    assert len(app.wires) == 1, 'duplicate wire was added'
    dialog.destroy()
    app.number()
    assert app.wires[0].number == '001'
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'project.json'
        with patch('kiwiremanager.filedialog.asksaveasfilename', return_value=str(path)):
            assert app.save()
        assert load_project(path)[0] == app.wires
        csv_path = Path(temporary) / 'wires.csv'
        with patch('kiwiremanager.filedialog.asksaveasfilename', return_value=str(csv_path)):
            app.export()
        assert csv_path.exists()
    assert hashes(folder) == before, 'original schematic changed'
    print('PASS import GUI, explicit endpoints, duplicate protection, numbering, JSON, CSV, source hashes')
    print('sheets=%d roots=%d nets=%d terminals=%d diagnostics=%d' % (
        len(result.sheets), len(result.roots), len(result.nets),
        sum(len(n.terminals) for n in result.nets), len(result.diagnostics)))
finally:
    root.destroy()
