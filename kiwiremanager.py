"""Run with: python kiwiremanager.py"""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from wire_model import Numbering, Wire, assign_numbers, export_csv, issues, load_project, save_project


class Application:
    def __init__(self, root):
        self.root = root
        self.wires = []
        self.path = None
        self.dirty = False
        root.title('KiWire Manager — 線番管理')
        root.geometry('1060x650')
        root.minsize(850, 520)
        root.protocol('WM_DELETE_WINDOW', self.close)
        toolbar = ttk.Frame(root, padding=10)
        toolbar.pack(fill='x')
        for title, command in [('新規', self.new), ('開く', self.open),
                               ('保存', self.save), ('名前を付けて保存', lambda: self.save(True)),
                               ('CSV出力', self.export)]:
            ttk.Button(toolbar, text=title, command=command).pack(side='left', padx=3)
        numbering = ttk.LabelFrame(root, text='自動採番（既存線番を保持し、未採番のみ一覧順に割当）', padding=10)
        numbering.pack(fill='x', padx=10)
        self.prefix, self.start, self.digits = tk.StringVar(), tk.StringVar(value='1'), tk.StringVar(value='3')
        for title, variable in [('接頭辞', self.prefix), ('開始番号', self.start), ('最小桁数', self.digits)]:
            ttk.Label(numbering, text=title).pack(side='left', padx=4)
            ttk.Entry(numbering, textvariable=variable, width=12).pack(side='left')
            variable.trace_add('write', self.changed)
        ttk.Button(numbering, text='自動採番', command=self.number).pack(side='left', padx=12)
        ttk.Button(numbering, text='検証', command=self.check).pack(side='left')
        table_frame = ttk.Frame(root, padding=10)
        table_frame.pack(fill='both', expand=True)
        self.columns = ('number', 'source_device', 'source_terminal', 'target_device', 'target_terminal')
        self.labels = ('線番', '接続元機器', '接続元端子', '接続先機器', '接続先端子')
        self.table = ttk.Treeview(table_frame, columns=self.columns, show='headings', selectmode='browse')
        for column, title in zip(self.columns, self.labels):
            self.table.heading(column, text=title)
            self.table.column(column, width=150)
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.table.bind('<<TreeviewSelect>>', self.select)
        editor = ttk.LabelFrame(root, text='電線入力（線番は空欄で登録できます）', padding=10)
        editor.pack(fill='x', padx=10)
        self.inputs = {}
        for i, (column, title) in enumerate(zip(self.columns, self.labels)):
            ttk.Label(editor, text=title).grid(row=0, column=i, sticky='w')
            variable = tk.StringVar()
            self.inputs[column] = variable
            ttk.Entry(editor, textvariable=variable, width=19).grid(row=1, column=i, padx=(0, 8), sticky='ew')
            editor.columnconfigure(i, weight=1)
        actions = ttk.Frame(root, padding=10)
        actions.pack(fill='x')
        for title, command in [('追加', self.add), ('選択行を更新', self.update),
                               ('入力クリア', self.clear)]:
            ttk.Button(actions, text=title, command=command).pack(side='left', padx=3)
        ttk.Label(actions, text='入力後は「追加」または「選択行を更新」で確定してください。').pack(side='left', padx=10)
        self.status = tk.StringVar(value='電線を登録して自動採番してください。')
        ttk.Label(root, textvariable=self.status, padding=10).pack(fill='x')

    def changed(self, *args):
        self.dirty = True
        self.root.title(f'KiWire Manager — {self.path.name if self.path else "新規プロジェクト"} *')

    def clean(self):
        self.dirty = False
        self.root.title(f'KiWire Manager — {self.path.name if self.path else "新規プロジェクト"}')

    def settings(self):
        try:
            settings = Numbering(self.prefix.get(), int(self.start.get()), int(self.digits.get()))
        except ValueError as exc:
            raise ValueError('開始番号と桁数は整数で指定してください。') from exc
        settings.validate()
        return settings

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for wire in self.wires:
            self.table.insert('', 'end', iid=wire.wire_id, values=[getattr(wire, c) for c in self.columns])
        self.status.set(f'電線 {len(self.wires)}本 / 未採番 {sum(not w.number for w in self.wires)}本')

    def select(self, event=None):
        selection = self.table.selection()
        if selection:
            wire = next(w for w in self.wires if w.wire_id == selection[0])
            for column, variable in self.inputs.items():
                variable.set(getattr(wire, column))

    def clear(self):
        for variable in self.inputs.values():
            variable.set('')
        self.table.selection_remove(*self.table.selection())

    def input_wire(self, wire_id=None):
        values = {column: variable.get().strip() for column, variable in self.inputs.items()}
        if wire_id:
            values['wire_id'] = wire_id
        wire = Wire(**values)
        errors = issues([wire], include_unnumbered=False)
        if any(w.number and w.number == wire.number and w.wire_id != wire.wire_id for w in self.wires):
            errors.append('その線番はすでに使用されています。')
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
            self.status.set(f'{count}本に線番を割り当てました。')
        except ValueError as exc:
            messagebox.showerror('採番できません', str(exc), parent=self.root)

    def check(self):
        errors = issues(self.wires)
        messagebox.showinfo('検証結果', '\n'.join(errors) if errors else '問題はありません。', parent=self.root)

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel('未保存の変更', '変更を保存しますか？', parent=self.root)
        return self.save() if answer is True else answer is False

    def new(self):
        if self.confirm_discard():
            self.wires, self.path = [], None
            self.prefix.set('')
            self.start.set('1')
            self.digits.set('3')
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
            wires, settings = load_project(path)
            self.wires, self.path = wires, Path(path)
            self.prefix.set(settings.prefix)
            self.start.set(str(settings.start))
            self.digits.set(str(settings.digits))
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
            save_project(path, self.wires, self.settings())
            self.path = path
            self.clean()
            self.status.set(f'保存しました: {path}')
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror('保存エラー', str(exc), parent=self.root)
            return False

    def export(self):
        errors = issues(self.wires)
        if errors:
            messagebox.showerror('CSV出力できません', '\n'.join(errors), parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.csv',
                                           filetypes=[('配線表CSV', '*.csv')])
        if path:
            try:
                export_csv(path, self.wires)
                self.status.set(f'CSV出力しました: {path}')
            except (OSError, ValueError) as exc:
                messagebox.showerror('CSV出力エラー', str(exc), parent=self.root)

    def close(self):
        if self.confirm_discard():
            self.root.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    Application(window)
    window.mainloop()
