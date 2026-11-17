"""Explicit confirmation of copied marker text ownership."""
import tkinter as tk
from tkinter import ttk, messagebox
from wire_model import display_net_name


DECLINE_ALL = object()


def choose_net(parent, sheet, identifier, text, choices, suggested=None):
    result = []
    dialog = tk.Toplevel(parent)
    dialog.title('管理テキストの追加確認')
    dialog.transient(parent)
    ttk.Label(dialog, text=f'シート: {sheet}\n文字: {text}\nUUID: {identifier}\nこのテキストを管理するネットを選択してください。', padding=10).pack(anchor='w')
    keys = list(choices)
    labels = [f'{display_net_name(key)}  [内部識別: {key}]' for key in keys]
    selected = tk.StringVar(value=labels[keys.index(suggested)] if suggested in keys else '')
    combo = ttk.Combobox(dialog, textvariable=selected, values=labels, state='readonly', width=90)
    combo.pack(padx=10, pady=8)
    def accept():
        if combo.current() < 0:
            messagebox.showinfo('ネット選択', '登録先のネットを選択してください。', parent=dialog)
            return
        result.append(keys[combo.current()])
        dialog.destroy()
    ttk.Button(dialog, text='管理対象に追加', command=accept).pack(side='left', padx=10, pady=10)
    ttk.Button(dialog, text='追加しない', command=dialog.destroy).pack(side='left', padx=10)
    def decline_all():
        result.append(DECLINE_ALL)
        dialog.destroy()
    ttk.Button(dialog, text='全て追加しない', command=decline_all).pack(side='left', padx=10)
    dialog.grab_set()
    parent.wait_window(dialog)
    return result[0] if result else None
