"""Real Tk checks for bulk registration and embedded tabs, without KiCad CLI."""
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import tkinter as tk
from kicad_import import ImportResult, ImportedNet, Sheet, SheetRef, Terminal
from kiwiremanager import Application
from wire_model import load_project


def wait_idle(root, app):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        root.update()
        if str(app.import_button['state']) == 'normal':
            return
        time.sleep(0.01)
    raise AssertionError('import did not finish')


settings_folder = tempfile.TemporaryDirectory()
root = tk.Tk()
root.withdraw()
try:
    app = Application(root, settings_path=Path(settings_folder.name) / "settings.json")
    assert app.include_single_terminal is False
    app.include_single_terminal = True  # Explicitly include all nets for bulk-registration checks.
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        main, child = folder / 'main.kicad_sch', folder / 'child.kicad_sch'
        result = ImportResult(folder, {
            main: Sheet(main, [], [SheetRef('child', 'child.kicad_sch', child),
                                   SheetRef('missing', 'absent.kicad_sch', None, 'missing')]),
            child: Sheet(child, [])}, [main], ['Missing: absent.kicad_sch'], [
            ImportedNet('N1', 'N1', 'main', [Terminal('A', '1'), Terminal('B', '2'), Terminal('C', '3')]),
            ImportedNet('N2', 'N2', 'main', [Terminal('D', '1'), Terminal('E', '2')]),
            ImportedNet('N3', 'N3', 'main', [Terminal('F', '1')])])
        with patch('kiwiremanager.import_folder', return_value=result), \
                patch('kiwiremanager.filedialog.askdirectory', return_value=temporary):
            app.import_kicad()
            wait_idle(root, app)
            assert len(app.wires) == 4
            identities = [w.wire_id for w in app.wires]
            app.import_kicad()
            wait_idle(root, app)
            assert [w.wire_id for w in app.wires] == identities
        assert len(app.notebook.tabs()) == 4
        hierarchy = app.import_tabs.hierarchy
        main_item = hierarchy.get_children()[0]
        assert len(hierarchy.get_children(main_item)) == 2
        assert 'absent.kicad_sch' in app.import_tabs.diagnostics.get('1.0', 'end')
        app.number()
        assert [w.number for w in app.wires] == ['001', '001', '002', '003']
        path = folder / 'project.json'
        with patch('kiwiremanager.filedialog.asksaveasfilename', return_value=str(path)):
            assert app.save()
        assert load_project(path)[0] == app.wires
        with patch('kiwiremanager.messagebox.showerror') as error:
            app.export()
        assert error.called, 'incomplete physical wire must not be exported'
        with patch('kiwiremanager.import_folder', side_effect=ValueError('import failed')), \
                patch('kiwiremanager.filedialog.askdirectory', return_value=temporary), \
                patch('kiwiremanager.messagebox.showerror'):
            app.import_kicad()
            wait_idle(root, app)
        assert [w.wire_id for w in app.wires] == identities
        assert 'import failed' in app.import_tabs.diagnostics.get('1.0', 'end')
        app.new()
        assert not app.import_tabs.hierarchy.get_children()
        assert app.import_result is None
        assert not app.wires
        release = threading.Event()

        def delayed_import(folder):
            release.wait(3)
            return result

        with patch('kiwiremanager.import_folder', side_effect=delayed_import), \
                patch('kiwiremanager.filedialog.askdirectory', return_value=temporary):
            app.import_kicad()
            app.new()
            release.set()
            wait_idle(root, app)
        assert not app.wires, 'stale import must not modify a new project'
        app.include_single_terminal = False
        assert app.include_single_terminal is False
        dialog = app.open_settings()
        dialog.include_single_terminal.set(True)
        dialog.destroy()
        assert app.include_single_terminal is False, 'cancel must discard changes'
        assert not app.settings_path.exists()
        dialog = app.open_settings()
        dialog.include_single_terminal.set(False)
        dialog.apply()
        assert app.include_single_terminal is False
        restarted_root = tk.Toplevel(root)
        restarted = Application(restarted_root, settings_path=app.settings_path)
        assert restarted.include_single_terminal is False, 'saved settings must survive restart'
        restarted_root.destroy()
        dialog = app.open_settings()
        dialog.include_single_terminal.set(True)
        with patch('kiwiremanager.save_settings', side_effect=PermissionError('read only')), \
                patch('kiwiremanager.messagebox.showerror') as save_error:
            dialog.apply()
        assert save_error.called
        assert dialog.winfo_exists()
        assert app.include_single_terminal is False
        dialog.destroy()
        app.apply_import(result)
        assert len(app.wires) == 3
        assert {w.net_name for w in app.wires} == {'N1', 'N2'}
        assert 'N3' not in app.import_tabs.diagnostics.get('1.0', 'end')
        dialog = app.open_settings()
        dialog.include_single_terminal.set(True)
        dialog.apply()
        app.apply_import(result)
        assert len(app.wires) == 4
        app.include_single_terminal = False
        app.apply_import(result)
        assert len(app.wires) == 4, 'turning off must not delete registered rows'
        assert len(app.notebook.tabs()) == 4
        app.wires[0].net_name = 'C:/project/main.kicad_sch::Power'
        app.refresh()
        app.table.selection_set(app.wires[0].wire_id)
        app.select()
        assert app.inputs['net_name'].get() == 'Power'
        assert app.table.item(app.wires[0].wire_id, 'values')[0] == 'Power'
        app.inputs['source_terminal'].set('99')
        app.update()
        assert app.wires[0].net_name == 'C:/project/main.kicad_sch::Power'
        assert not any(isinstance(w, tk.Toplevel) for w in root.winfo_children())
    print('PASS bulk registration, chain order, 4 tabs, hierarchy/warnings, repeat import, numbering, JSON, failure and stale import')
    print('PASS settings default, cancel, apply, single-terminal include/exclude, existing row retention')
    print('PASS persisted preferences, restart restore, failed save preserves current setting and dialog')
finally:
    root.destroy()
    settings_folder.cleanup()
