"""Read-only per-net view of imported and registered connections."""
import tkinter as tk
from collections import defaultdict
from tkinter import ttk
from wire_model import display_net_name


def net_rows(wires, imported=None, include_single_terminal=True):
    groups = defaultdict(list)
    for wire in wires:
        if wire.net_name.strip():
            groups[wire.net_name].append(wire)
    catalogs = {net.key: net for net in imported.nets} if imported else {}
    keys = dict.fromkeys([*groups, *catalogs])
    result = []
    for key in keys:
        registered = groups[key]
        net = catalogs.get(key)
        numbers = list(dict.fromkeys(w.number for w in registered if w.number))
        endpoints = {(device, pin) for w in registered
                     for device, pin in ((w.source_device, w.source_terminal), (w.target_device, w.target_terminal))
                     if device and pin}
        terminal_count = len(net.terminals) if net else len(endpoints)
        if not include_single_terminal and terminal_count == 1:
            continue
        root = net.root if net else (key.rsplit('.kicad_sch::', 1)[0] if '.kicad_sch::' in key else '')
        if net and not registered:
            state = '電線未登録'
        elif len(numbers) > 1:
            state = '線番不一致'
        elif any(not w.number for w in registered):
            state = '未採番あり'
        else:
            state = '採番済み'
        name = net.name if net and hasattr(net, 'name') else display_net_name(key)
        if name.startswith('/'):
            name = name.rsplit('/', 1)[-1]
        result.append((key, (name, ', '.join(numbers), len(registered), terminal_count, state, root)))
    return result


class NetsTab:
    def __init__(self, notebook, changed=None, number_all=None):
        self.changed = changed
        self.keys = {}
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text='ネット一覧')
        ttk.Label(self.frame, text='ネット選択後に線番を入力・反映できます。空欄で固定解除。端子数は取込情報があればその件数、なければ登録済み電線から集計します。').pack(anchor='w')
        editor = ttk.Frame(self.frame)
        editor.pack(fill='x', pady=8)
        ttk.Label(editor, text='固定線番（例：P24）').pack(side='left')
        self.number = tk.StringVar()
        self.number_entry = ttk.Entry(editor, textvariable=self.number, width=20)
        self.number_entry.pack(side='left', padx=8)
        self.number_entry.bind('<Return>', self.apply_on_enter)
        self.number_entry.bind('<KP_Enter>', self.apply_on_enter)
        ttk.Button(editor, text='線番を反映', command=self.apply).pack(side='left')
        ttk.Button(editor, text='残りのネットを採番', command=number_all).pack(side='left', padx=8)
        self.table = ttk.Treeview(self.frame, columns=('name','number','wires','terminals','state','root'), show='headings')
        for column, title, width in zip(self.table['columns'], ('ネット名','線番','電線数','端子数','状態','ルート'), (200,100,70,70,120,250)):
            self.table.heading(column, text=title)
            self.table.column(column, width=width)
        self.table.bind('<<TreeviewSelect>>', self.select)
        scroll = ttk.Scrollbar(self.frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)

    def show(self, wires, imported=None, include_single_terminal=True):
        self.keys = {}
        self.number.set('')
        self.table.delete(*self.table.get_children())
        for index, (key, values) in enumerate(net_rows(wires, imported, include_single_terminal)):
            self.keys[str(index)] = key
            self.table.insert('', 'end', iid=str(index), values=values)

    def select(self, event=None):
        selection = self.table.selection()
        if selection:
            self.number.set(self.table.item(selection[0], 'values')[1])

    def apply(self):
        selection = self.table.selection()
        if not self.changed:
            return
        target_key = None
        if selection:
            rows = list(self.table.get_children())
            index = rows.index(selection[0])
            target_key = self.keys[rows[min(index + 1, len(rows) - 1)]]
        succeeded = self.changed(self.keys[selection[0]] if selection else None, self.number.get().strip())
        if succeeded is True and target_key is not None:
            target = next((row for row, key in self.keys.items() if key == target_key), None)
            if target is not None:
                self.table.selection_set(target)
                self.table.focus(target)
                self.table.see(target)
                self.select()
                self.number_entry.focus_set()
                self.number_entry.selection_range(0, 'end')

    def apply_on_enter(self, event=None):
        if self.table.selection():
            self.apply()
        return 'break'
