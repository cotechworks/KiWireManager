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
from kiwiremanager import Application
from wire_model import load_project


def hashes(folder):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*.kicad_sch')}


folder = Path(sys.argv[1])
before = hashes(folder)
settings_folder = tempfile.TemporaryDirectory()
root = tk.Tk()
root.withdraw()
try:
    app = Application(root, settings_path=Path(settings_folder.name) / "settings.json")
    app.include_single_terminal = True  # This smoke test intentionally checks every imported net.
    with patch('kiwiremanager.filedialog.askdirectory', return_value=str(folder)), \
            patch('kiwiremanager.messagebox.showerror') as errors:
        app.import_kicad()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            root.update()
            if app.import_result is not None:
                break
            if errors.called:
                raise AssertionError(ascii(errors.call_args))
            time.sleep(0.02)
        assert app.import_result is not None, 'import did not finish'
    result = app.import_result
    assert {w.net_name for w in app.wires} == {n.key for n in result.nets}
    assert len(app.wires) == sum(max(1, len(n.terminals) - 1) for n in result.nets)
    assert len(app.notebook.tabs()) == 4
    assert not any(isinstance(w, tk.Toplevel) for w in root.winfo_children())
    assert len(app.import_tabs.hierarchy.get_children()) == len(result.roots)
    app.number()
    assert app.wires[0].number == '001'
    numbers = {}
    for wire in app.wires:
        if wire.net_name in numbers:
            assert numbers[wire.net_name] == wire.number
        numbers[wire.net_name] = wire.number
    assert len(set(numbers.values())) == len(result.nets)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'project.json'
        with patch('kiwiremanager.filedialog.asksaveasfilename', return_value=str(path)):
            assert app.save()
        assert load_project(path)[0] == app.wires
        csv_path = Path(temporary) / 'wires.csv'
        incomplete = [w for w in app.wires if not all((w.source_device, w.source_terminal, w.target_device, w.target_terminal))]
        if incomplete:
            with patch('kiwiremanager.messagebox.showerror') as errors:
                app.export()
            assert errors.called
            assert not csv_path.exists()
        all_wires = app.wires
        try:
            app.wires = [w for w in all_wires if w not in incomplete]
            with patch('kiwiremanager.filedialog.asksaveasfilename', return_value=str(csv_path)):
                app.export()
            assert csv_path.exists()
        finally:
            app.wires = all_wires
    assert hashes(folder) == before, 'original schematic changed'
    print('PASS bulk import GUI, all nets, 4 tabs, numbering, JSON, complete-row CSV, incomplete-row export block, source hashes')
    print('rows=%d incomplete_rows=%d' % (len(app.wires), len(incomplete)))
    print('sheets=%d roots=%d nets=%d terminals=%d diagnostics=%d' % (
        len(result.sheets), len(result.roots), len(result.nets),
        sum(len(n.terminals) for n in result.nets), len(result.diagnostics)))
finally:
    root.destroy()
    settings_folder.cleanup()
