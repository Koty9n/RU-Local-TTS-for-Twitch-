"""Окно выбора голосов: при установке (install.ps1 -> --installer) и в программе («Голоса» → «Скачать голоса…»).

Выбор при установке пишется в data/voices.choice (имя голоса на строку) — повторный запуск установщика не
спрашивает снова и не докачивает то, от чего отказались. Только tkinter, окно открывается лишь по требованию.
"""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ui_theme import C, FONT, FONT_B, apply_theme, github_link

GLADOS = "GLaDOS"
PIPER_MB = 61
# имя, ~МБ, подпись
CATALOG = [(GLADOS, 210, "русская GLaDOS из Portal · самый большой"),
           ("IGM", PIPER_MB, ""), ("Mari", PIPER_MB, ""), ("Women", PIPER_MB, ""), ("Сказочник", PIPER_MB, "")]
CHOICE_FILE = "voices.choice"
GLADOS_MODEL = Path("tera/model/TeraTTS/glados2-g2p-vits/exported/model.onnx")   # относительно data/
HOVER = "#26262c"
ACCENT_MB = 355   # модели ударений RUAccent: нужны любому голосу, качаются один раз (data/ruaccent + koziev)


def accents_ready(root):
    return (Path(root) / "data" / "ruaccent" / "nn" / "nn_omograph").is_dir()


def installed(root):
    """Какие голоса из каталога уже скачаны."""
    root = Path(root)
    have = {n for n, _, _ in CATALOG[1:] if (root / "voices" / f"{n}.onnx").exists()}
    if (root / "data" / GLADOS_MODEL).exists():
        have.add(GLADOS)
    return have


def read_choice(data):
    """-> список выбранных при установке или None, если выбора ещё не было."""
    try:
        lines = (Path(data) / CHOICE_FILE).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def write_choice(data, names):
    (Path(data) / CHOICE_FILE).write_text(
        "# выбор голосов при установке (правится вручную; удалишь файл — установщик спросит снова)\n"
        + "\n".join(names) + "\n", encoding="utf-8")


class Picker:
    """on_done(список имён) после «Скачать»; on_done(None) — закрыли окно (если close_is_ok=False).
    countdown > 0 — через столько секунд скачивается текущий выбор (для установки без присмотра)."""

    def __init__(self, master, have=(), on_done=None, countdown=0, close_is_ok=False,
                 title="Голоса для TTS", button="Скачать", need_accents=False,
                 hint="Отметь, какие скачать. Остальные можно докачать потом:\n«Голоса» → «Скачать голоса…»"):
        self.have, self.on_done, self.close_is_ok = set(have), on_done, close_is_ok
        self.need_accents = need_accents   # ударений ещё нет — к любому выбору добавятся ~355 МБ
        self.win = tk.Toplevel(master) if master is not None else tk.Tk()
        w = self.win
        if master is None:
            apply_theme(w)
        else:
            w.transient(master)
            w.grab_set()   # из программы — модальное: пока окно открыто, главное не нажимается
        w.configure(bg=C["bg"])
        w.title(title)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        self.sel = {n: n not in self.have for n, _, _ in CATALOG}
        self.left = countdown

        f = ttk.Frame(w, padding=20)
        f.pack(fill="both", expand=True)
        tk.Label(f, text=title, bg=C["bg"], fg=C["fg"], font=("Segoe UI Semibold", 14)).pack(anchor="w")
        ttk.Label(f, text=hint, style="Mut.TLabel", justify="left").pack(anchor="w", pady=(4, 12))

        box = ttk.Frame(f, style="Card.TFrame", padding=4)
        box.pack(fill="x")
        self.rows = {}
        for i, (name, mb, note) in enumerate(CATALOG):
            self.rows[name] = self._row(box, name, mb, note)
            if i == 0:   # GLaDOS отдельно от обычных голосов — тонкая линия
                tk.Frame(box, bg=C["line"], height=1).pack(fill="x", padx=8, pady=2)

        self.total = ttk.Label(f, text="", font=FONT_B)
        self.total.pack(anchor="w", pady=(12, 0))
        self.timer = ttk.Label(f, text="", style="Mut.TLabel")
        self.timer.pack(anchor="w")

        bt = ttk.Frame(f)
        bt.pack(fill="x", pady=(16, 0))
        self.btn_go = ttk.Button(bt, text=button, style="Accent.TButton", command=self.go)
        self.btn_go.pack(side="right")
        self.btn_all = ttk.Button(bt, text="Все", command=self.toggle_all)
        self.btn_all.pack(side="right", padx=8)
        github_link(bt).pack(side="left")
        self.refresh()
        w.bind("<Return>", lambda e: self.go())
        w.bind("<Escape>", lambda e: self.close())
        for ev in ("<Button>", "<Key>"):   # привязка к окну действует на все его элементы, но не на другие окна
            w.bind(ev, self._stop_timer, add="+")
        if countdown:
            w.after(1000, self._tick)
        w.update_idletasks()
        # по центру экрана и на передний план (из установщика окно иначе может открыться под консолью)
        x = (w.winfo_screenwidth() - w.winfo_width()) // 2
        y = (w.winfo_screenheight() - w.winfo_height()) // 3
        w.geometry(f"+{max(0, x)}+{max(0, y)}")
        w.lift()
        w.attributes("-topmost", True)
        w.after(300, lambda: w.attributes("-topmost", False))
        w.focus_force()

    # ---- строка: квадрат-галочка, имя (+подпись), размер; щелчок по всей строке
    def _row(self, box, name, mb, note):
        have = name in self.have
        r = tk.Frame(box, bg=C["card"], padx=10, pady=8, cursor="" if have else "hand2")
        r.pack(fill="x")
        cv = tk.Canvas(r, width=20, height=20, bg=C["card"], highlightthickness=0)
        cv.pack(side="left", padx=(0, 12))
        txt = tk.Frame(r, bg=C["card"])
        txt.pack(side="left", fill="x", expand=True)
        nm = tk.Label(txt, text=name, bg=C["card"], fg=C["fg"], font=FONT_B, anchor="w")
        nm.pack(anchor="w")
        sub = None
        if note:
            sub = tk.Label(txt, text=note, bg=C["card"], fg=C["mut"], font=("Segoe UI", 9), anchor="w")
            sub.pack(anchor="w")
        size = tk.Label(r, text="уже есть" if have else f"~{mb} МБ", bg=C["card"],
                        fg=C["ok"] if have else C["mut"], font=FONT)
        size.pack(side="right")
        parts = [r, cv, txt, nm, size] + ([sub] if sub else [])
        if not have:
            for p in parts:
                p.bind("<Button-1>", lambda e, n=name: self.toggle(n))
                p.bind("<Enter>", lambda e, ps=parts: [q.configure(bg=HOVER) for q in ps])
                p.bind("<Leave>", lambda e, ps=parts: [q.configure(bg=C["card"]) for q in ps])
        return cv

    def _draw(self, name):
        cv = self.rows[name]
        cv.delete("all")
        if name in self.have:
            cv.create_rectangle(2, 2, 18, 18, outline=C["ok"], width=1.5)
            cv.create_line(6, 10, 9, 13, 14, 7, fill=C["ok"], width=2, capstyle="round", joinstyle="round")
        elif self.sel[name]:
            cv.create_rectangle(2, 2, 18, 18, fill=C["acc"], outline=C["acc"])
            cv.create_line(6, 10, 9, 13, 14, 7, fill="#ffffff", width=2, capstyle="round", joinstyle="round")
        else:
            cv.create_rectangle(2, 2, 18, 18, outline=C["mut"], width=1.5)

    def chosen(self):
        return [n for n, _, _ in CATALOG if self.sel[n] and n not in self.have]

    def refresh(self):
        for n in self.rows:
            self._draw(n)
        ch = self.chosen()
        mb = sum(m for n, m, _ in CATALOG if n in ch)
        if not ch:
            self.total.configure(text="Ничего не выбрано" if len(self.have) < len(CATALOG) else "Все голоса уже скачаны",
                                 foreground=C["mut"])
        else:
            word = "голос" if len(ch) == 1 else ("голоса" if len(ch) < 5 else "голосов")
            extra = ""
            if self.need_accents:
                mb += ACCENT_MB
                extra = " вместе с ударениями"
            self.total.configure(text=f"{len(ch)} {word} · скачается ~{mb} МБ{extra}", foreground=C["fg"])
        self.btn_go.state(["!disabled"] if ch else ["disabled"])
        free = [n for n, _, _ in CATALOG if n not in self.have]
        self.btn_all.configure(text="Снять все" if free and all(self.sel[n] for n in free) else "Все")

    def toggle(self, name):
        self.sel[name] = not self.sel[name]
        self.refresh()

    def toggle_all(self):
        free = [n for n, _, _ in CATALOG if n not in self.have]
        on = not all(self.sel[n] for n in free)
        for n in free:
            self.sel[n] = on
        self.refresh()

    # ---- обратный отсчёт: любое нажатие его останавливает
    def _tick(self):
        if self.left <= 0:
            return
        self.left -= 1
        if self.left == 0:
            self.go()
            return
        self.timer.configure(text=f"Через {self.left} с начнётся загрузка выбранного")
        self.win.after(1000, self._tick)

    def _stop_timer(self, _e=None):
        if self.left:
            self.left = 0
            self.timer.configure(text="")

    def _finish(self, result):
        self.win.destroy()
        if self.on_done:
            self.on_done(result)

    def go(self):
        ch = self.chosen()
        if ch:
            self._finish(ch)

    def close(self):
        self._finish(self.chosen() if self.close_is_ok else None)


def run_installer(data, root):
    """Режим установщика: показать окно, записать выбор в data/voices.choice. Код 0 — выбор записан."""
    have = installed(root)
    if have >= {n for n, _, _ in CATALOG}:
        write_choice(data, [n for n, _, _ in CATALOG])
        return 0
    result = []
    p = Picker(None, have, on_done=result.append, countdown=60, close_is_ok=True,
               need_accents=not accents_ready(root))
    p.win.mainloop()
    chosen = (result[0] if result else None) or []
    if not chosen and not have:      # совсем без голосов программе нечего делать — берём все
        chosen = [n for n, _, _ in CATALOG]
    write_choice(data, sorted(set(chosen) | have, key=[n for n, _, _ in CATALOG].index))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--installer":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        sys.exit(run_installer(sys.argv[2], sys.argv[3]))
    print("Запуск: python voice_picker.py --installer <папка data> <папка программы>")
    sys.exit(2)
