"""Preview imported sheets/nets and explicitly select a physical wire."""
import tkinter as tk
from tkinter import messagebox, ttk

from wire_model import Wire


class ImportDialog(tk.Toplevel):
    def __init__(self, parent, result, add_wire):
        super().__init__(parent)
        self.title('KiCad取込 — 階層・ネット・接続端子')
        self.geometry('1100x750')
        self.result = result
        self.add_wire = add_wire
        ttk.Label(self, text=f'{len(result.sheets)}ファイル / {len(result.roots)}ルート / {len(result.nets)}ネット。端子を選び、物理電線を1本ずつ登録します。', padding=8).pack(fill='x')
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=8)
        net_frame, sheet_frame, diagnostic_frame = ttk.Frame(notebook), ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(net_frame, text='ネットと端子')
        notebook.add(sheet_frame, text='シート階層')
        notebook.add(diagnostic_frame, text=f'不足・警告 ({len(result.diagnostics)})')
        self.net_table = ttk.Treeview(net_frame, columns=('root', 'name', 'pins'), show='headings', selectmode='browse')
        for column, title, width in [('root', 'ルート', 260), ('name', 'ネット名', 550), ('pins', '端子数', 60)]:
            self.net_table.heading(column, text=title)
            self.net_table.column(column, width=width)
        scroll = ttk.Scrollbar(net_frame, command=self.net_table.yview)
        self.net_table.configure(yscrollcommand=scroll.set)
        self.net_table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        for index, net in enumerate(result.nets):
            self.net_table.insert('', 'end', iid=str(index), values=(net.root, net.name, len(net.terminals)))
        self.net_table.bind('<<TreeviewSelect>>', self.select_net)
        hierarchy = ttk.Treeview(sheet_frame, columns=('file',), show='tree headings')
        hierarchy.heading('#0', text='シート配置')
        hierarchy.heading('file', text='ファイル／不足理由')
        hierarchy.column('#0', width=430)
        sheet_scroll = ttk.Scrollbar(sheet_frame, command=hierarchy.yview)
        hierarchy.configure(yscrollcommand=sheet_scroll.set)
        hierarchy.pack(side='left', fill='both', expand=True)
        sheet_scroll.pack(side='right', fill='y')

        def add_sheet(parent_id, path, title):
            item = hierarchy.insert(parent_id, 'end', text=title, values=(str(path.relative_to(result.folder)),), open=True)
            for ref in result.sheets[path].refs:
                if ref.reason:
                    hierarchy.insert(item, 'end', text=ref.name, values=(f'不足: {ref.filename} ({ref.reason})',))
                else:
                    add_sheet(item, ref.target, ref.name)

        for root in result.roots:
            add_sheet('', root, root.name)
        text = tk.Text(diagnostic_frame, wrap='word')
        text.pack(fill='both', expand=True)
        text.insert('1.0', '\n'.join(result.diagnostics) or '不足・警告はありません。')
        text.configure(state='disabled')
        endpoints = ttk.LabelFrame(self, text='選択ネット内の物理電線（配線経路は自動推定しません）', padding=8)
        endpoints.pack(fill='x', padx=8, pady=8)
        self.source = ttk.Combobox(endpoints, state='readonly', width=65)
        self.target = ttk.Combobox(endpoints, state='readonly', width=65)
        ttk.Label(endpoints, text='接続元').grid(row=0, column=0)
        ttk.Label(endpoints, text='接続先').grid(row=1, column=0)
        self.source.grid(row=0, column=1, sticky='ew')
        self.target.grid(row=1, column=1, sticky='ew')
        endpoints.columnconfigure(1, weight=1)
        ttk.Button(endpoints, text='電線として追加', command=self.add_selected).grid(row=0, column=2, rowspan=2, padx=8)
        self.status = tk.StringVar(value='ネットを選択してください。1端子のネットは一覧確認のみ可能です。')
        ttk.Label(self, textvariable=self.status, padding=8).pack(fill='x')

    def select_net(self, event=None):
        selected = self.net_table.selection()
        if not selected:
            return
        net = self.result.nets[int(selected[0])]
        values = [terminal.label for terminal in net.terminals]
        self.source.configure(values=values)
        self.target.configure(values=values)
        self.source.set('')
        self.target.set('')
        self.status.set(f'{net.name}: {len(values)}端子。接続元・接続先を明示的に選択してください。')

    def add_selected(self):
        selected = self.net_table.selection()
        if not selected or self.source.current() < 0 or self.target.current() < 0:
            messagebox.showinfo('電線登録', 'ネットと接続元・接続先を選択してください。', parent=self)
            return
        if self.source.current() == self.target.current():
            messagebox.showerror('電線登録', '異なる端子を選択してください。', parent=self)
            return
        net = self.result.nets[int(selected[0])]
        source, target = net.terminals[self.source.current()], net.terminals[self.target.current()]
        wire = Wire(source_device=source.device, source_terminal=source.pin,
                    target_device=target.device, target_terminal=target.pin, net_name=net.key)
        if self.add_wire(wire):
            self.status.set('電線を追加しました。メイン画面で「3桁通し番号を採番」を押してください。')
