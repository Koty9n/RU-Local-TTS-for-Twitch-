"""Тёмная тема окон Twitch TTS (окно программы и выбор голосов). Только tkinter, без сторонних библиотек."""
from tkinter import ttk

# цвета — те же, что у панели OBS (panel_html.py), чтобы окна и док выглядели одной программой
C = {"bg": "#18181b", "card": "#202024", "field": "#141417", "btn": "#2c2c33", "line": "#33333b",
     "fg": "#efeff1", "mut": "#a0a0ab", "acc": "#9147ff", "acc_hi": "#a970ff",
     "ok": "#2ecc71", "warn": "#f1c40f", "bad": "#ff6b6f"}
FONT, FONT_B, MONO = ("Segoe UI", 10), ("Segoe UI Semibold", 10), ("Consolas", 9)


def apply_theme(root):
    """Тёмная тема на встроенной теме clam — без сторонних библиотек."""
    root.configure(bg=C["bg"])
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=C["bg"], foreground=C["fg"], fieldbackground=C["field"], bordercolor=C["line"],
                lightcolor=C["line"], darkcolor=C["line"], troughcolor=C["field"], focuscolor=C["acc"],
                selectbackground=C["acc"], selectforeground="#ffffff", insertcolor=C["fg"], font=FONT)
    s.configure("Card.TFrame", background=C["card"])
    s.configure("Card.TLabel", background=C["card"])
    s.configure("Mut.TLabel", foreground=C["mut"])
    s.configure("CardMut.TLabel", background=C["card"], foreground=C["mut"])
    s.configure("H.TLabel", background=C["card"], foreground=C["mut"], font=("Segoe UI Semibold", 9))
    s.configure("TButton", background=C["btn"], padding=(12, 6), borderwidth=1)
    s.map("TButton", background=[("disabled", C["card"]), ("pressed", C["line"]), ("active", C["line"])],
          foreground=[("disabled", C["mut"])], bordercolor=[("active", C["acc"]), ("focus", C["acc"])])
    s.configure("Accent.TButton", background=C["acc"], foreground="#ffffff", bordercolor=C["acc"], font=FONT_B)
    s.map("Accent.TButton", background=[("disabled", C["btn"]), ("pressed", C["acc"]), ("active", C["acc_hi"])],
          foreground=[("disabled", C["mut"])], bordercolor=[("disabled", C["line"]), ("active", C["acc_hi"])])
    s.configure("TEntry", padding=6, insertcolor=C["fg"])
    s.map("TEntry", bordercolor=[("focus", C["acc"])], fieldbackground=[("readonly", C["field"])])
    s.configure("TCombobox", padding=5, arrowcolor=C["mut"], background=C["btn"])
    s.map("TCombobox", fieldbackground=[("readonly", C["field"])], foreground=[("readonly", C["fg"])],
          bordercolor=[("focus", C["acc"])], background=[("active", C["line"])])
    s.configure("TCheckbutton", indicatorbackground=C["field"], indicatorforeground="#ffffff")
    s.map("TCheckbutton", indicatorbackground=[("selected", C["acc"])], background=[("active", C["bg"])])
    # вкладки без рамок: у выбранной — фон карточки и фиолетовая черта сверху
    s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0),
                bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"])
    s.configure("TNotebook.Tab", background=C["bg"], foreground=C["mut"], padding=(16, 8), borderwidth=1,
                bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"])
    s.map("TNotebook.Tab", background=[("selected", C["card"]), ("active", C["card"])],
          foreground=[("selected", C["fg"]), ("active", C["fg"])],
          lightcolor=[("selected", C["acc"])], bordercolor=[("selected", C["card"])])
    s.configure("TLabelframe", background=C["bg"], bordercolor=C["line"])
    s.configure("TLabelframe.Label", background=C["bg"], foreground=C["mut"])
    s.configure("Vertical.TScrollbar", background=C["btn"], arrowcolor=C["mut"], bordercolor=C["bg"])
    s.configure("TProgressbar", background=C["acc"], bordercolor=C["line"])
    # выпадающий список комбобокса — обычный tk.Listbox, красим через option_add
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["acc"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")


def card(parent, **pack):
    """Карточка: фон чуть светлее окна, отступ 12 — как .card в панели."""
    f = ttk.Frame(parent, style="Card.TFrame", padding=12)
    f.pack(fill="x", **({"pady": (0, 8)} | pack))
    return f
