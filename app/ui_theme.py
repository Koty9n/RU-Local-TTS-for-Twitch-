"""Тёмная тема окон Twitch TTS (окно программы и выбор голосов). Только tkinter, без сторонних библиотек."""
import tkinter as tk
import webbrowser
from tkinter import ttk

GITHUB = "https://github.com/Koty9n/RU-Local-TTS-for-Twitch-"   # то же в tts_core.py (для панели OBS)

# цвета — те же, что у панели OBS (panel_html.py), чтобы окна и док выглядели одной программой
C = {"bg": "#18181b", "card": "#202024", "field": "#141417", "btn": "#2c2c33", "line": "#33333b",
     "fg": "#efeff1", "mut": "#a0a0ab", "acc": "#9147ff", "acc_hi": "#a970ff",
     "ok": "#2ecc71", "warn": "#f1c40f", "bad": "#ff6b6f", "tab": "#2a2340"}
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
    s.configure("Slim.TButton", padding=(8, 6))   # ряд из многих кнопок в узком окне
    s.configure("SlimAccent.TButton", padding=(8, 6), background=C["acc"], foreground="#ffffff",
                bordercolor=C["acc"], font=FONT_B)
    s.map("SlimAccent.TButton", background=[("pressed", C["acc"]), ("active", C["acc_hi"])])
    s.configure("Danger.TButton", foreground=C["bad"], padding=(8, 6))
    s.map("Danger.TButton", bordercolor=[("active", C["bad"]), ("focus", C["bad"])])
    # галочка — свои картинки: у clam вместо галочки крестик ☒
    off, on = _check_images(root)
    if "Tick.indicator" not in s.element_names():   # повторный apply_theme в той же программе
        s.element_create("Tick.indicator", "image", off, ("selected", on), sticky="w")
    s.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
        ("Tick.indicator", {"side": "left", "sticky": ""}),
        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [("Checkbutton.label", {"sticky": "nswe"})]})]})])
    s.map("TCheckbutton", background=[("active", C["bg"])])
    # вкладки без рамок: выбранная — фиолетовый оттенок, яркий текст и фиолетовая черта сверху
    s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0),
                bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"])
    s.configure("TNotebook.Tab", background=C["bg"], foreground=C["mut"], padding=(16, 8), borderwidth=2,
                bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"])
    s.map("TNotebook.Tab", background=[("selected", C["tab"]), ("active", C["card"])],
          foreground=[("selected", "#ffffff"), ("active", C["fg"])],
          lightcolor=[("selected", C["acc"])], bordercolor=[("selected", C["acc"])])
    s.configure("TLabelframe", background=C["bg"], bordercolor=C["line"])
    s.configure("TLabelframe.Label", background=C["bg"], foreground=C["mut"])
    s.configure("Vertical.TScrollbar", background=C["btn"], arrowcolor=C["mut"], bordercolor=C["bg"])
    s.configure("TProgressbar", background=C["acc"], bordercolor=C["line"])
    # выпадающий список комбобокса — обычный tk.Listbox, красим через option_add
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["acc"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")


def _check_images(root):
    """Квадратики для галочки: пустой с рамкой и фиолетовый с белой «птичкой». Размер — под масштаб экрана."""
    n = max(14, round(16 * float(root.tk.call("tk", "scaling")) / 1.333))
    gap = n // 2   # прозрачная полоска справа — отступ до текста
    off, on = (tk.PhotoImage(master=root, width=n + gap, height=n) for _ in range(2))
    off.put(C["mut"], to=(0, 0, n, n))
    off.put(C["field"], to=(1, 1, n - 1, n - 1))
    on.put(C["acc"], to=(0, 0, n, n))
    t = max(2, n // 8)   # толщина «птички»
    for a, b in (((0.22, 0.52), (0.42, 0.72)), ((0.42, 0.72), (0.80, 0.30))):
        for i in range(n * 2):
            x = round((a[0] + (b[0] - a[0]) * i / (n * 2)) * n)
            y = round((a[1] + (b[1] - a[1]) * i / (n * 2)) * n)
            on.put("#ffffff", to=(x, y - t // 2, x + t, y - t // 2 + t))
    root._tick_images = (off, on)   # иначе картинки соберёт сборщик мусора
    return off, on


def github_link(parent, bg=None):
    """Строка-ссылка на страницу проекта: серая, при наведении фиолетовая, щелчок открывает браузер."""
    lbl = tk.Label(parent, text="RU-Local-TTS for Twitch · GitHub ↗", bg=bg or C["bg"], fg=C["mut"],
                   font=("Segoe UI", 9), cursor="hand2")
    lbl.bind("<Button-1>", lambda e: webbrowser.open(GITHUB))
    lbl.bind("<Enter>", lambda e: lbl.config(fg=C["acc_hi"]))
    lbl.bind("<Leave>", lambda e: lbl.config(fg=C["mut"]))
    return lbl


def card(parent, **pack):
    """Карточка: фон чуть светлее окна, отступ 12 — как .card в панели."""
    f = ttk.Frame(parent, style="Card.TFrame", padding=12)
    f.pack(fill="x", **({"pady": (0, 8)} | pack))
    return f
