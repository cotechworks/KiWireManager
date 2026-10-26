"""Embedded main-window tabs for schematic hierarchy and import diagnostics."""
import tkinter as tk
from tkinter import ttk


class ImportTabs:
    def __init__(self, notebook):
        self.notebook = notebook
        self.sheet_frame = ttk.Frame(notebook)
        self.diagnostic_frame = ttk.Frame(notebook)
        notebook.add(self.sheet_frame, text='シート階層')
        notebook.add(self.diagnostic_frame, text='不足・警告')
        self.hierarchy = ttk.Treeview(self.sheet_frame, columns=('file',), show='tree headings')
        self.hierarchy.heading('#0', text='シート配置')
        self.hierarchy.heading('file', text='ファイル／不足理由')
        self.hierarchy.column('#0', width=400)
        scroll = ttk.Scrollbar(self.sheet_frame, command=self.hierarchy.yview)
        self.hierarchy.configure(yscrollcommand=scroll.set)
        self.hierarchy.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.diagnostics = tk.Text(self.diagnostic_frame, wrap='word', state='disabled')
        warning_scroll = ttk.Scrollbar(self.diagnostic_frame, command=self.diagnostics.yview)
        self.diagnostics.configure(yscrollcommand=warning_scroll.set)
        self.diagnostics.pack(side='left', fill='both', expand=True)
        warning_scroll.pack(side='right', fill='y')
        self.clear()

    def set_diagnostics(self, messages):
        self.diagnostics.configure(state='normal')
        self.diagnostics.delete('1.0', 'end')
        self.diagnostics.insert('1.0', '\n'.join(messages) if messages else '不足・警告はありません。')
        self.diagnostics.configure(state='disabled')
        self.notebook.tab(self.diagnostic_frame, text=f'不足・警告 ({len(messages)})')

    def clear(self):
        self.hierarchy.delete(*self.hierarchy.get_children())
        self.set_diagnostics(['回路図はまだ取り込まれていません。'])
        self.notebook.tab(self.diagnostic_frame, text='不足・警告')

    def show_result(self, result, extra_messages=()):
        self.hierarchy.delete(*self.hierarchy.get_children())

        def add_sheet(parent_id, path, title):
            item = self.hierarchy.insert(parent_id, 'end', text=title,
                values=(str(path.relative_to(result.folder)),), open=True)
            for ref in result.sheets[path].refs:
                if ref.reason:
                    self.hierarchy.insert(item, 'end', text=ref.name,
                        values=(f'不足: {ref.filename} ({ref.reason})',))
                else:
                    add_sheet(item, ref.target, ref.name)

        for root in result.roots:
            add_sheet('', root, root.name)
        self.set_diagnostics(list(result.diagnostics) + list(extra_messages))
