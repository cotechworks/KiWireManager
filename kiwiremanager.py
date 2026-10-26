"""Run with: python kiwiremanager.py"""
import tkinter as tk
import queue
import threading
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from wire_model import Numbering, Wire, assign_numbers, export_csv, issues, load_project, save_project, display_net_name
from kicad_import import import_folder, merge_imported_wires
from kicad_dialog import ImportTabs
from wiring_types import collect_wiring_types, clear_excluded_numbers, excluded_nets
from wiring_types_tab import WiringTypesTab
from settings_dialog import SettingsDialog
from app_settings import default_settings_path, load_settings, save_settings
from schematic_writeback import prepare_writeback, execute_writeback, MissingAnnotations, RecoveryRequired, recover_transaction


class Application:
    def __init__(self, root, settings_path=None):
        self.root = root
        self.wires = []
        self.annotations = []
        self.path = None
        self.dirty = False
        self.import_result = None
        self.import_generation = 0
        self.include_single_terminal = False
        self.settings_path = Path(settings_path) if settings_path is not None else default_settings_path()
        settings_error = None
        try:
            self.include_single_terminal = load_settings(self.settings_path)
        except (OSError, ValueError) as exc:
            settings_error = str(exc)
        root.title('KiWire Manager — 線番管理')
        root.geometry('1060x650')
        root.minsize(850, 520)
        root.protocol('WM_DELETE_WINDOW', self.close)
        toolbar = ttk.Frame(root, padding=10)
        toolbar.pack(fill='x')
        self.import_button = ttk.Button(toolbar, text='KiCadフォルダー取込', command=self.import_kicad)
        self.import_button.pack(side='left', padx=3)
        self.write_button = ttk.Button(toolbar, text='回路図へ書込', command=self.write_schematic)
        self.write_button.pack(side='left', padx=3)
        for title, command in [('新規', self.new), ('開く', self.open),
                               ('保存', self.save), ('名前を付けて保存', lambda: self.save(True)),
                               ('CSV出力', self.export), ('設定', self.open_settings)]:
            ttk.Button(toolbar, text=title, command=command).pack(side='left', padx=3)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True, padx=10)
        self.wire_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.wire_tab, text='電線一覧')
        self.wiring_tab = WiringTypesTab(self.notebook, self.set_wiring_type)
        self.import_tabs = ImportTabs(self.notebook)
        numbering = ttk.LabelFrame(self.wire_tab, text='ネットの初出順に001〜999を割当。同じネットは線番を共有。未設定は保留します。', padding=10)
        numbering.pack(fill='x', padx=10)
        self.numbering_settings = Numbering()
        ttk.Button(numbering, text='3桁通し番号を採番', command=self.number).pack(side='left', padx=12)
        ttk.Button(numbering, text='検証', command=self.check).pack(side='left')
        table_frame = ttk.Frame(self.wire_tab, padding=10)
        table_frame.pack(fill='both', expand=True)
        self.columns = ('net_name', 'number', 'source_device', 'source_terminal', 'target_device', 'target_terminal')
        self.labels = ('ネット名', '線番（自動）', '接続元機器', '接続元端子', '接続先機器', '接続先端子')
        self.table = ttk.Treeview(table_frame, columns=self.columns, show='headings', selectmode='browse')
        for column, title in zip(self.columns, self.labels):
            self.table.heading(column, text=title)
            self.table.column(column, width=150)
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.table.bind('<<TreeviewSelect>>', self.select)
        editor = ttk.LabelFrame(self.wire_tab, text='電線入力（取込順の仮配線は編集可能。接続先空欄の行も採番できます）', padding=10)
        editor.pack(fill='x', padx=10)
        self.inputs = {}
        for i, (column, title) in enumerate(zip(self.columns, self.labels)):
            ttk.Label(editor, text=title).grid(row=0, column=i, sticky='w')
            variable = tk.StringVar()
            self.inputs[column] = variable
            ttk.Entry(editor, textvariable=variable, width=15, state='readonly' if column == 'number' else 'normal').grid(row=1, column=i, padx=(0, 8), sticky='ew')
            editor.columnconfigure(i, weight=1)
        actions = ttk.Frame(self.wire_tab, padding=10)
        actions.pack(fill='x')
        for title, command in [('追加', self.add), ('選択行を更新', self.update),
                               ('入力クリア', self.clear)]:
            ttk.Button(actions, text=title, command=command).pack(side='left', padx=3)
        ttk.Label(actions, text='入力後は「追加」または「選択行を更新」で確定してください。').pack(side='left', padx=10)
        self.status = tk.StringVar(value='ネット名と電線の接続情報を入力してください。')
        ttk.Label(root, textvariable=self.status, padding=10).pack(fill='x')
        if settings_error:
            root.after_idle(lambda: messagebox.showwarning('設定読込エラー',
                f'設定を読み込めないため初期値を使用します。\n{self.settings_path}\n{settings_error}', parent=root))

    def changed(self, *args):
        self.dirty = True
        self.root.title(f'KiWire Manager — {self.path.name if self.path else "新規プロジェクト"} *')

    def run_write_task(self, action, success, failure):
        self.write_button.configure(state='disabled')
        self.import_button.configure(state='disabled')
        progress = tk.Toplevel(self.root)
        progress.title('回路図書込')
        progress.transient(self.root)
        progress.protocol('WM_DELETE_WINDOW', lambda: None)
        ttk.Label(progress, text='回路図を検証・処理しています…', padding=24).pack()
        progress.grab_set()
        output = queue.Queue()
        def work():
            try:
                output.put((action(), None))
            except Exception as exc:
                output.put((None, exc))
        def poll():
            try:
                result, error = output.get_nowait()
            except queue.Empty:
                self.root.after(100, poll)
                return
            progress.destroy()
            self.write_button.configure(state='normal')
            self.import_button.configure(state='normal')
            if error is not None:
                failure(error)
            else:
                success(result)
        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, poll)

    def write_schematic(self, recreate_missing=False):
        if self.import_result is None:
            messagebox.showinfo('回路図書込', '先に回路図フォルダーを取り込んでください。', parent=self.root)
            return
        if str(self.import_button['state']) == 'disabled':
            messagebox.showinfo('回路図書込', '取込が完了してから実行してください。', parent=self.root)
            return
        if self.path is None and not self.save():
            return
        imported = self.import_result
        wires, settings, annotations = deepcopy(self.wires), deepcopy(self.settings()), deepcopy(self.annotations)
        def failure(error):
            if isinstance(error, MissingAnnotations):
                if messagebox.askyesno('削除された線番テキスト', f'{error}\n\n再作成しますか？', parent=self.root):
                    self.write_schematic(recreate_missing=True)
                return
            if isinstance(error, RecoveryRequired):
                if messagebox.askyesno('未完了の書込', f'{error}\n\n前回処理前の状態へ復元しますか？', parent=self.root):
                    def recovered(result):
                        self.wires, self.numbering_settings, self.annotations = load_project(self.path)
                        self.reset_import()
                        self.refresh()
                        self.clear()
                        self.clean()
                        messagebox.showinfo('復元完了', '回路図とJSONを復元しました。図面を再取込してください。', parent=self.root)
                    self.run_write_task(lambda: recover_transaction(error.journal, imported.folder, self.path),
                        recovered,
                        lambda exc: messagebox.showerror('復元エラー', str(exc), parent=self.root))
                return
            self.import_tabs.set_diagnostics([str(error)])
            self.notebook.select(self.import_tabs.diagnostic_frame)
            messagebox.showerror('回路図書込エラー', str(error), parent=self.root)
        def preview(plan):
            self.import_tabs.set_diagnostics(plan.warnings)
            if not plan.updates:
                messagebox.showinfo('回路図書込', '変更する線番テキストはありません。', parent=self.root)
                return
            additions = sum(edit.old_number is None for edit in plan.edits)
            updates = sum(edit.old_number is not None and edit.number is not None and edit.old_number != edit.number for edit in plan.edits)
            deletions = sum(edit.number is None for edit in plan.edits)
            targets = [p.name for p in plan.updates if p != plan.project_path]
            warning_text = '\n'.join(plan.warnings[:12])
            if len(plan.warnings) > 12:
                warning_text += f'\nほか{len(plan.warnings)-12}件（不足・警告タブに表示）'
            text = (f'追加{additions}箇所・更新{updates}箇所・削除{deletions}箇所\n対象図面: ' + ', '.join(targets)
                    + f'\n\nバックアップ先: {imported.folder / "backup"}\n回路図とプロジェクトJSONを更新します。')
            if warning_text:
                text += '\n\n対象外・警告:\n' + warning_text
            if not messagebox.askyesno('書込内容の確認', text + '\n\n実行しますか？', parent=self.root):
                return
            def completed(backup):
                self.annotations = plan.annotations
                self.clean()
                self.status.set(f'回路図への線番書込が完了しました。バックアップ: {backup}')
                messagebox.showinfo('書込完了', f'バックアップ: {backup}', parent=self.root)
            self.run_write_task(lambda: execute_writeback(plan), completed, failure)
        self.run_write_task(lambda: prepare_writeback(imported, wires, settings, annotations, self.path, recreate_missing), preview, failure)

    def import_kicad(self):
        folder = filedialog.askdirectory(parent=self.root, title='回路図を含むフォルダーを選択（サブフォルダーも検索）')
        if not folder:
            return
        self.import_button.configure(state='disabled')
        self.import_generation += 1
        generation = self.import_generation
        include_single_terminal = self.include_single_terminal
        self.status.set('回路図の階層とネットを読み込んでいます…')
        output = queue.Queue()

        def work():
            try:
                output.put((import_folder(folder), None))
            except Exception as exc:
                output.put((None, str(exc)))

        def poll():
            try:
                result, error = output.get_nowait()
            except queue.Empty:
                self.root.after(100, poll)
                return
            self.import_button.configure(state='normal')
            if generation != self.import_generation:
                return
            if not error:
                try:
                    self.apply_import(result, include_single_terminal)
                except ValueError as exc:
                    error = str(exc)
            if error:
                self.status.set('KiCad取込に失敗しました。電線一覧は変更していません。')
                self.import_tabs.set_diagnostics([error])
                self.notebook.select(self.import_tabs.diagnostic_frame)
                messagebox.showerror('KiCad取込エラー', error, parent=self.root)

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, poll)

    def open_settings(self):
        def apply(value):
            try:
                save_settings(self.settings_path, value)
            except (OSError, ValueError) as exc:
                messagebox.showerror('設定保存エラー', f'{self.settings_path}\n{exc}', parent=self.root)
                return False
            self.include_single_terminal = value
            return True
        return SettingsDialog(self.root, self.include_single_terminal, apply)

    def apply_import(self, result, include_single_terminal=None):
        if include_single_terminal is None:
            include_single_terminal = self.include_single_terminal
        types, mapping, wiring_warnings = collect_wiring_types(result)
        previous = deepcopy(self.settings())
        for kind in types:
            self.settings().wire_types.setdefault(kind, True)
        self.settings().net_wire_types.update(mapping)
        if previous != self.settings():
            self.changed()
        nets = [net for net in result.nets if include_single_terminal or len(net.terminals) != 1]
        skipped = len(result.nets) - len(nets)
        wires = merge_imported_wires(self.wires, nets)
        added = len(wires) - len(self.wires)
        self.wires = wires
        self.import_result = result
        removed = clear_excluded_numbers(self.wires, self.settings())
        if added or removed:
            self.changed()
        incomplete = [net for net in nets if len(net.terminals) < 2]
        messages = [f'接続先未確定（{len(net.terminals)}端子）: {net.root} / {net.name}' for net in incomplete]
        self.import_tabs.show_result(result, messages + wiring_warnings)
        self.refresh()
        self.clear()
        self.notebook.select(self.wire_tab)
        self.status.set(f'{len(nets)}ネット取込・{added}行追加。1端子ネット{skipped}件除外。接続先未確定{len(incomplete)}ネット。')

    def set_wiring_type(self, key, enabled):
        self.settings().wire_types[key] = enabled
        clear_excluded_numbers(self.wires, self.settings())
        self.changed()
        self.refresh()
        self.clear()
        self.status.set(f'採番対象外 {len(excluded_nets(self.settings()))}ネット。回路図の線番削除は「回路図へ書込」で反映します。')

    def add_imported_wire(self, wire):
        endpoints = {(wire.source_device, wire.source_terminal), (wire.target_device, wire.target_terminal)}
        for existing in self.wires:
            other = {(existing.source_device, existing.source_terminal), (existing.target_device, existing.target_terminal)}
            if existing.net_name == wire.net_name and endpoints == other:
                messagebox.showinfo('電線登録', '同じ端子間の電線は登録済みです。', parent=self.root)
                return False
        self.wires.append(wire)
        self.changed()
        self.refresh()
        return True

    def clean(self):
        self.dirty = False
        self.root.title(f'KiWire Manager — {self.path.name if self.path else "新規プロジェクト"}')

    def settings(self):
        return self.numbering_settings

    def refresh(self):
        self.wiring_tab.show(self.settings().wire_types, self.settings().net_wire_types)
        self.table.delete(*self.table.get_children())
        for wire in self.wires:
            self.table.insert('', 'end', iid=wire.wire_id, values=[display_net_name(wire.net_name) if c == 'net_name' else getattr(wire, c) for c in self.columns])
        self.status.set(f'電線 {len(self.wires)}本 / ネット名未設定 {sum(not w.net_name.strip() for w in self.wires)}本')

    def select(self, event=None):
        selection = self.table.selection()
        if selection:
            wire = next(w for w in self.wires if w.wire_id == selection[0])
            for column, variable in self.inputs.items():
                variable.set(display_net_name(wire.net_name) if column == 'net_name' else getattr(wire, column))

    def clear(self):
        for variable in self.inputs.values():
            variable.set('')
        self.table.selection_remove(*self.table.selection())

    def input_wire(self, wire_id=None):
        values = {column: variable.get().strip() for column, variable in self.inputs.items()}
        if wire_id:
            values['wire_id'] = wire_id
        previous = next((w for w in self.wires if w.wire_id == wire_id), None)
        if previous and values['net_name']:
            visible = display_net_name(previous.net_name)
            if visible != previous.net_name:
                prefix = previous.net_name[:len(previous.net_name) - len(visible)] if visible else previous.net_name
                values['net_name'] = prefix + values['net_name']
        values['number'] = previous.number if previous and previous.net_name == values['net_name'] else ''
        wire = Wire(**values)
        errors = issues([wire], include_unnumbered=False)
        if errors:
            raise ValueError('\n'.join(errors))
        return wire

    def add(self):
        try:
            self.wires.append(self.input_wire())
            self.changed()
            self.refresh()
            self.clear()
        except ValueError as exc:
            messagebox.showerror('入力エラー', str(exc), parent=self.root)

    def update(self):
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo('電線の更新', '更新する行を選択してください。', parent=self.root)
            return
        try:
            wire = self.input_wire(selection[0])
            index = next(i for i, w in enumerate(self.wires) if w.wire_id == wire.wire_id)
            self.wires[index] = wire
            clear_excluded_numbers(self.wires, self.settings())
            self.changed()
            self.refresh()
            self.table.selection_set(wire.wire_id)
        except ValueError as exc:
            messagebox.showerror('入力エラー', str(exc), parent=self.root)

    def number(self):
        try:
            count = assign_numbers(self.wires, self.settings())
            if count:
                self.changed()
            self.refresh()
            self.clear()
            self.status.set(f'{count}本の線番を反映しました。ネット名未設定は{sum(not w.net_name.strip() for w in self.wires)}本です。')
        except ValueError as exc:
            messagebox.showerror('採番できません', str(exc), parent=self.root)

    def check(self):
        errors = issues(self.wires, settings=self.settings())
        messagebox.showinfo('検証結果', '\n'.join(errors) if errors else '問題はありません。', parent=self.root)

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel('未保存の変更', '変更を保存しますか？', parent=self.root)
        return self.save() if answer is True else answer is False

    def new(self):
        if self.confirm_discard():
            self.wires, self.path = [], None
            self.annotations = []
            self.reset_import()
            self.numbering_settings = Numbering()
            self.refresh()
            self.clear()
            self.clean()

    def open(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self.root, filetypes=[('線番プロジェクト', '*.json')])
        if not path:
            return
        try:
            wires, settings, annotations = load_project(path)
            self.wires, self.path = wires, Path(path)
            self.annotations = annotations
            self.reset_import()
            self.numbering_settings = settings
            self.refresh()
            self.clear()
            self.clean()
        except (OSError, ValueError) as exc:
            messagebox.showerror('読込エラー', str(exc), parent=self.root)

    def save(self, save_as=False):
        path = self.path
        if save_as or path is None:
            chosen = filedialog.asksaveasfilename(parent=self.root, defaultextension='.json',
                                                 filetypes=[('線番プロジェクト', '*.json')])
            if not chosen:
                return False
            path = Path(chosen)
        try:
            save_project(path, self.wires, self.settings(), self.annotations)
            self.path = path
            self.clean()
            self.status.set(f'保存しました: {path}')
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror('保存エラー', str(exc), parent=self.root)
            return False

    def export(self):
        errors = issues(self.wires, settings=self.settings())
        if errors:
            messagebox.showerror('CSV出力できません', '\n'.join(errors), parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.csv',
                                           filetypes=[('配線表CSV', '*.csv')])
        if path:
            try:
                export_csv(path, self.wires, self.settings())
                self.status.set(f'CSV出力しました: {path}')
            except (OSError, ValueError) as exc:
                messagebox.showerror('CSV出力エラー', str(exc), parent=self.root)

    def close(self):
        if self.confirm_discard():
            self.root.destroy()

    def reset_import(self):
        self.import_generation += 1
        self.import_result = None
        self.import_tabs.clear()
        self.wiring_tab.show({}, {})
        self.notebook.select(self.wire_tab)


if __name__ == '__main__':
    window = tk.Tk()
    Application(window)
    window.mainloop()
