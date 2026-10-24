"""Exercise writer GUI confirmation/recovery with isolated, mocked backend I/O."""
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from kiwiremanager import Application
from schematic_writeback import MissingAnnotations, RecoveryRequired
from wire_model import Wire, TextAnnotation


def wait(root, app):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        root.update()
        if str(app.write_button['state']) == 'normal':
            return
        time.sleep(0.01)
    raise AssertionError('write did not complete')


root = tk.Tk()
root.withdraw()
try:
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        app = Application(root, settings_path=folder / 'settings.json')
        app.path = folder / 'project.json'
        app.wires = [Wire('J1', '1', 'J2', '1', '001', net_name='N')]
        app.save()
        imported = SimpleNamespace(folder=folder)
        app.import_result = imported
        annotation = TextAnnotation('main.kicad_sch', '11111111-1111-4111-8111-111111111111', 'N', '001')
        plan = SimpleNamespace(updates={folder / 'main.kicad_sch': b'test'},
            project_path=app.path, edits=[SimpleNamespace(old_number=None, number='001')],
            warnings=['unplaced net'], annotations=[annotation])
        with patch('kiwiremanager.prepare_writeback', return_value=plan), \
                patch('kiwiremanager.execute_writeback', return_value=folder / 'backup') as execute, \
                patch('kiwiremanager.messagebox.askyesno', return_value=True), \
                patch('kiwiremanager.messagebox.showinfo'):
            app.write_schematic()
            wait(root, app)
            assert execute.called
            assert app.annotations == [annotation]
            assert not app.dirty
        with patch('kiwiremanager.prepare_writeback', return_value=plan), \
                patch('kiwiremanager.execute_writeback') as execute, \
                patch('kiwiremanager.messagebox.askyesno', return_value=False):
            app.write_schematic()
            wait(root, app)
            assert not execute.called
        with patch('kiwiremanager.prepare_writeback', side_effect=[MissingAnnotations(['deleted text']), plan]) as prepare, \
                patch('kiwiremanager.execute_writeback', return_value=folder / 'backup'), \
                patch('kiwiremanager.messagebox.askyesno', return_value=True), \
                patch('kiwiremanager.messagebox.showinfo'):
            app.write_schematic()
            wait(root, app)
            assert prepare.call_args.args[-1] is True
        with patch('kiwiremanager.prepare_writeback', side_effect=ValueError('manual edit')), \
                patch('kiwiremanager.messagebox.showerror') as error:
            app.write_schematic()
            wait(root, app)
            assert error.called
            assert 'manual edit' in app.import_tabs.diagnostics.get('1.0', 'end')
        with patch('kiwiremanager.prepare_writeback', side_effect=RecoveryRequired(folder / 'backup/writeback.json')), \
                patch('kiwiremanager.recover_transaction') as recover, \
                patch('kiwiremanager.messagebox.askyesno', return_value=True), \
                patch('kiwiremanager.messagebox.showinfo'):
            app.write_schematic()
            wait(root, app)
            assert recover.called
            assert app.import_result is None
        print('PASS writer GUI preview, cancel, deleted UUID recreation, conflict, recovery, and JSON reload')
finally:
    root.destroy()
