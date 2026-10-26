"""Embedded, scrollable checkboxes for imported physical wire properties."""
import tkinter as tk
from tkinter import ttk

from wiring_types import WiringType


class WiringTypesTab:
    def __init__(self, notebook, changed):
        self.changed = changed
        self.variables, self.checks = {}, {}
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text='配線の種類')
        ttk.Label(self.frame, text='採番する配線の種類にチェックを入れてください。初期値はすべてオンです。').pack(anchor='w')
        ttk.Label(self.frame, text='同じネットにあるすべての種類をオフにすると、そのネット全体を採番から除外します。').pack(anchor='w')
        ttk.Label(self.frame, text='既定値は図面に保存された指定です。種類を特定できないネットは除外しません。').pack(anchor='w')
        area = ttk.Frame(self.frame)
        area.pack(fill='both', expand=True, pady=(10, 0))
        self.canvas = tk.Canvas(area, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.rows = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.rows, anchor='nw')
        self.rows.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.summary = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.summary).pack(anchor='w', pady=(8, 0))

    def show(self, types, mapping):
        for child in self.rows.winfo_children():
            child.destroy()
        self.variables, self.checks = {}, {}
        for column, title in enumerate(('採番対象', '線のスタイル', '線幅', '線の色', 'ネット数')):
            ttk.Label(self.rows, text=title).grid(row=0, column=column, sticky='w', padx=8, pady=4)
            self.rows.columnconfigure(column, weight=1 if column in (1, 2, 3) else 0)
        for row, (key, enabled) in enumerate(types.items(), 1):
            variable = tk.BooleanVar(value=enabled)
            self.variables[key] = variable
            def toggle(kind=key, state=variable):
                self.changed(kind, state.get())
            check = ttk.Checkbutton(self.rows, variable=variable, command=toggle)
            check.grid(row=row, column=0, sticky='w', padx=8, pady=4)
            self.checks[key] = check
            count = sum(key in kinds for kinds in mapping.values())
            for column, label in enumerate((*WiringType.from_key(key).labels, count), 1):
                ttk.Label(self.rows, text=label).grid(row=row, column=column, sticky='w', padx=8, pady=4)
        unknown = sum(not kinds for kinds in mapping.values())
        self.summary.set(f'配線の種類 {len(types)}件 / 種類を特定できないネット {unknown}件')
