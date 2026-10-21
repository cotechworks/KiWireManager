"""Import preferences saved when the user confirms the dialog."""
import tkinter as tk
from tkinter import ttk


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, include_single_terminal, on_apply):
        super().__init__(parent)
        self.title('設定')
        self.resizable(False, False)
        self.transient(parent)
        self.on_apply = on_apply
        self.include_single_terminal = tk.BooleanVar(value=include_single_terminal)
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Checkbutton(frame, text='1端子のネットを取り込む',
                        variable=self.include_single_terminal).pack(anchor='w')
        ttk.Label(frame, text='次回の取込から適用します。登録済みの行は削除しません。\n「OK」で設定をファイルに保存し、次回起動時も引き継ぎます。', padding=(0, 12)).pack(anchor='w')
        buttons = ttk.Frame(frame)
        buttons.pack(anchor='e')
        ttk.Button(buttons, text='OK', command=self.apply).pack(side='left', padx=4)
        ttk.Button(buttons, text='キャンセル', command=self.destroy).pack(side='left')
        self.bind('<Escape>', lambda event: self.destroy())
        self.bind('<Return>', lambda event: self.apply())
        self.grab_set()

    def apply(self):
        if self.on_apply(self.include_single_terminal.get()) is not False:
            self.destroy()
