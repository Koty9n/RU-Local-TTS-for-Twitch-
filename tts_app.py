"""Окно Twitch TTS: подключение, настройки, добавление голосов. Панель для OBS запускается вместе с ним."""
import os
import queue
import shutil
import sys
import threading
import traceback
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import glados_setup
import tts_core as core
import twitch_auth
from panel_server import start_panel

import voice_picker
from ui_theme import C, FONT, FONT_B, MONO, apply_theme, card, github_link

STATUS = {
    "connected": ("Подключён к чату", C["ok"]),
    "connecting": ("Подключение…", C["warn"]),
    "error": ("Ошибка (см. журнал)", C["bad"]),
    "stopped": ("Не подключён", C["mut"]),
}


DEFAULT_DEVICE = "По умолчанию (системное)"
ACCENT_MODELS = ["tiny2", "tiny", "turbo3.1", "turbo3"]


class TTSWindow:
    def __init__(self):
        try:  # чёткий текст на HiDPI-экранах
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        self.cfg = core.load_cfg()
        self.bot = core.Bot(self.cfg)
        self.server, self.port = start_panel(self.bot, int(self.cfg.get("panel_port", 8765)))
        self.ui_q = queue.Queue()
        self.last_log = None
        self._asked_python = False
        self._glados_installed = glados_setup.engine_installed(core.BASE)

        self.root = tk.Tk()
        self.root.title("Twitch TTS")
        apply_theme(self.root)
        self._tick = 0
        self._ready_key = None
        try:  # иконка окна (assets/icon.ico лежит рядом с программой)
            self.root.iconbitmap(str(core.BASE / "assets" / "icon.ico"))
        except Exception:
            pass
        self.root.geometry("780x720")
        self.root.minsize(680, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        github_link(self.root).pack(side="bottom", anchor="e", padx=14, pady=(2, 6))   # видна на всех вкладках
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        self.build_home(nb)
        self.build_voices(nb)
        self.build_settings(nb)

        self.poll()
        self.bot.preload_engines()   # GLaDOS и ударения грузятся в фоне сразу, а не при первой фразе
        self.bot.ensure_glados(on_done=lambda ok: self.ui_q.put(lambda: self.glados_done(ok)))  # первый запуск: поставить GLaDOS
        if not self.bot.token:  # первый запуск: сразу ведём по шагам входа
            self.root.after(700, self.twitch_login_wizard)
        if self.cfg.get("autoconnect") and self.bot.token and self.bot.chan:
            self.connect()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/?k={self.cfg['panel_key']}"

    # ---------- вкладка «Главная» ----------
    def build_home(self, nb):
        f = ttk.Frame(nb, padding=(0, 12, 0, 0))
        nb.add(f, text="Главная")

        # 1) состояние — главное на экране: крупный статус, что звучит, главная кнопка
        st = card(f)
        top = ttk.Frame(st, style="Card.TFrame")
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=12, height=12, bg=C["card"], highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 11, 11, fill=C["mut"], outline="")
        self.dot.pack(side="left", padx=(0, 8))
        self.status_lbl = tk.Label(top, text="", font=("Segoe UI Semibold", 14), bg=C["card"], fg=C["fg"], anchor="w")
        self.status_lbl.pack(side="left")
        self.chan_lbl = ttk.Label(top, text="", style="CardMut.TLabel")
        self.chan_lbl.pack(side="right")
        self.now_lbl = ttk.Label(st, text="", style="CardMut.TLabel")
        self.now_lbl.pack(anchor="w", pady=(4, 12))
        row = ttk.Frame(st, style="Card.TFrame")
        row.pack(fill="x")
        self.btn_conn = ttk.Button(row, text="Подключиться", style="Accent.TButton", command=self.toggle_conn)
        self.btn_conn.pack(side="left")
        ttk.Button(row, text="Пропустить", command=lambda: self.bot.player.skip.set()).pack(side="left", padx=8)
        ttk.Button(row, text="Открыть панель", command=lambda: webbrowser.open(self.url)).pack(side="right")

        # 2) готовность — чек-лист первого запуска; когда всё ✓, остаётся одной тихой строкой
        rd = card(f)
        ttk.Label(rd, text="ГОТОВНОСТЬ", style="H.TLabel").pack(anchor="w", pady=(0, 6))
        self.ready_rows = {}
        for key, title, btn_text, cmd in (
                ("twitch", "Вход в Twitch", "Войти…", self.twitch_login_wizard),
                ("glados", "Голос GLaDOS", "Установить", self.install_glados),
                ("voices", "Голоса", None, None)):
            r = ttk.Frame(rd, style="Card.TFrame")
            r.pack(fill="x", pady=2)
            mark = tk.Label(r, text="○", width=2, bg=C["card"], fg=C["mut"], font=FONT_B, anchor="w")
            mark.pack(side="left")
            ttk.Label(r, text=title, style="Card.TLabel", width=16).pack(side="left")
            info = ttk.Label(r, text="", style="CardMut.TLabel")
            info.pack(side="left")
            b = ttk.Button(r, text=btn_text, command=cmd) if btn_text else None
            self.ready_rows[key] = (mark, info, b)

        # 3) OBS
        box = card(f)
        ttk.Label(box, text="ПАНЕЛЬ В OBS", style="H.TLabel").pack(anchor="w")
        ttk.Label(box, text="OBS → Док-панели → Пользовательские док-панели браузера → имя «TTS», адрес:",
                  style="CardMut.TLabel", wraplength=680).pack(anchor="w", pady=(4, 6))
        r2 = ttk.Frame(box, style="Card.TFrame")
        r2.pack(fill="x")
        self.url_var = tk.StringVar(value=self.url)
        ttk.Entry(r2, textvariable=self.url_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(r2, text="Копировать", command=self.copy_url).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="В адресе секретный ключ — не показывай его на стриме.", style="CardMut.TLabel"
                  ).pack(anchor="w", pady=(6, 0))

        # 4) журнал — тихий, внизу, занимает остаток
        lh = ttk.Frame(f)
        lh.pack(fill="x", pady=(4, 4))
        ttk.Label(lh, text="Журнал", style="Mut.TLabel").pack(side="left")
        lf = ttk.Frame(f)
        lf.pack(fill="both", expand=True)
        self.log_txt = tk.Text(lf, state="disabled", wrap="word", font=MONO, height=6, bg=C["field"], fg=C["mut"],
                               relief="flat", highlightthickness=1, highlightbackground=C["line"],
                               highlightcolor=C["line"], padx=8, pady=6, insertbackground=C["fg"])
        sb = ttk.Scrollbar(lf, command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_txt.pack(side="left", fill="both", expand=True)

    def update_ready(self):
        """Чек-лист «Готовность». Перерисовывается только когда что-то поменялось."""
        g = self.bot.glados
        installed = self._glados_installed
        tw = (True, self.bot.nick or self.cfg.get("channel") or "токен есть") if self.bot.token else (False, "нужно войти")
        if g.state == "installing":
            gl = (None, g.step or "устанавливается…")
        elif installed:
            gl = (True, "установлена · !tts glados")
        else:
            gl = (False, "не установлена")
        n = len(self.bot.voices.names())
        vo = (n > 0, f"{n}: " + ", ".join(self.bot.voices.names()) if n else "нет ни одного")
        rows = {"twitch": tw, "glados": gl, "voices": vo}
        key = repr(rows)
        if key == self._ready_key:
            return
        self._ready_key = key
        for k, (ok, text) in rows.items():
            mark, info, b = self.ready_rows[k]
            mark.configure(text={True: "✓", False: "○", None: "…"}[ok],
                           fg={True: C["ok"], False: C["warn"], None: C["warn"]}[ok])
            info.configure(text=text)
            if b is not None:
                if ok is False and not b.winfo_ismapped():
                    b.pack(side="right")
                elif ok is not False and b.winfo_ismapped():
                    b.pack_forget()

    def copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url)
        messagebox.showinfo("Скопировано", "Ссылка для OBS-дока скопирована.")

    def connect(self):
        try:
            self.bot.start()
        except core.BotError as e:
            messagebox.showwarning("Подключение", str(e))

    def toggle_conn(self):
        if self.bot.running():
            self.bot.stop()
        else:
            self.connect()

    # ---------- вкладка «Голоса» ----------
    def build_voices(self, nb):
        f = ttk.Frame(nb, padding=(0, 12, 0, 0))
        nb.add(f, text="Голоса")
        ttk.Label(f, text="Эти имена зрители используют так: !tts <имя>", style="Mut.TLabel", wraplength=680).pack(anchor="w")

        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, pady=8)
        self.voice_list = tk.Listbox(mid, font=("Segoe UI", 11), activestyle="none", bg=C["field"], fg=C["fg"],
                                     selectbackground=C["acc"], selectforeground="#ffffff", relief="flat",
                                     highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["acc"])
        sb = ttk.Scrollbar(mid, command=self.voice_list.yview)
        self.voice_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.voice_list.pack(side="left", fill="both", expand=True)

        btns = ttk.Frame(f)
        btns.pack(fill="x")
        ttk.Button(btns, text="Скачать голоса…", style="Accent.TButton", command=self.download_voices).pack(side="left")
        ttk.Button(btns, text="Добавить свой…", command=self.add_voice).pack(side="left", padx=6)
        ttk.Button(btns, text="Удалить", command=self.remove_voice).pack(side="left")
        ttk.Button(btns, text="По умолчанию", command=self.set_default_voice).pack(side="left", padx=6)
        ttk.Button(btns, text="Обновить", command=self.refresh_voices).pack(side="left")

        st = ttk.Frame(f)
        st.pack(fill="x", pady=(8, 0))
        self.glados_lbl = ttk.Label(st, text="")
        self.glados_lbl.pack(side="left")
        self.btn_glados = ttk.Button(st, text="Установить GLaDOS", command=self.install_glados)
        self.accent_lbl = ttk.Label(f, text="", style="Mut.TLabel")
        self.accent_lbl.pack(anchor="w", pady=(2, 0))

        t = ttk.LabelFrame(f, text="Проверка звучания", padding=8)
        t.pack(fill="x", pady=(10, 0))
        self.test_var = tk.StringVar(value="Привет, это проверка звука")
        ttk.Entry(t, textvariable=self.test_var).pack(side="left", fill="x", expand=True)
        ttk.Button(t, text="Озвучить выбранным", command=self.test_voice).pack(side="left", padx=(8, 0))
        self.refresh_voices()

    def refresh_voices(self):
        self.bot.voices.scan()
        self.voice_list.delete(0, "end")
        default = (self.cfg.get("default_voice") or "").lower()
        for n in self.bot.voices.names():
            self.voice_list.insert("end", n + ("   ← по умолчанию" if n == default else ""))
        if hasattr(self, "dev_combo"):
            self.v_voice_combo["values"] = self.bot.voices.names()

    def selected_voice(self):
        sel = self.voice_list.curselection()
        if not sel:
            return None
        return self.voice_list.get(sel[0]).split("   ")[0]

    def add_voice(self):
        onnx = filedialog.askopenfilename(
            title="Выбери файл модели голоса (.onnx)", filetypes=[("Модель Piper", "*.onnx"), ("Все файлы", "*.*")])
        if not onnx:
            return
        cfg_json = Path(onnx + ".json")
        if not cfg_json.exists():
            messagebox.showinfo("Нужен второй файл", "Рядом с моделью не найден файл настроек (.onnx.json). Выбери его.")
            p = filedialog.askopenfilename(title="Файл настроек (.onnx.json / .json)",
                                           filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
            if not p:
                return
            cfg_json = Path(p)
        name = simpledialog.askstring(
            "Название голоса", "Под каким именем вызывать голос в чате (!tts имя)?",
            initialvalue=core.suggest_voice_name(Path(onnx).stem), parent=self.root)
        if not name:
            return
        try:
            added = self.bot.voices.add_files(onnx, str(cfg_json), name)
        except Exception as e:
            messagebox.showerror("Не удалось добавить", str(e))
            return
        self.refresh_voices()
        messagebox.showinfo("Готово", f"Голос добавлен. В чате: !tts {added}")

    def remove_voice(self):
        n = self.selected_voice()
        if not n:
            return
        if not messagebox.askyesno("Удалить голос", f"Удалить «{n}» с диска?"):
            return
        try:
            self.bot.voices.remove(n)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
        self.refresh_voices()

    def set_default_voice(self):
        n = self.selected_voice()
        if n:
            self.cfg["default_voice"] = n
            core.save_cfg(self.cfg)
            self.v_voice.set(n)
            self.refresh_voices()

    def test_voice(self):
        try:
            self.bot.test_say(self.test_var.get(), self.selected_voice())
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # ---------- движки: GLaDOS и ударения ----------
    def install_glados(self):
        self.bot.glados.start(on_done=lambda ok: self.ui_q.put(lambda: self.glados_done(ok)))

    # ---------- «Скачать голоса…»: то же окно выбора, что и при установке ----------
    def download_voices(self):
        if getattr(self, "_dl_busy", False):
            messagebox.showinfo("Голоса", "Голоса уже скачиваются — ход загрузки виден в журнале.")
            return
        have = voice_picker.installed(core.BASE)
        if self.bot.glados.running():
            have.add(voice_picker.GLADOS)   # GLaDOS уже ставится — второй раз не предлагаем
        voice_picker.Picker(self.root, have, on_done=self._voices_chosen, title="Скачать голоса",
                            need_accents=not voice_picker.accents_ready(core.BASE),
                            hint="Отметь, какие скачать. Загрузка идёт в фоне,\nход — в журнале на «Главной».")

    def _voices_chosen(self, names):
        if not names:
            return
        if voice_picker.GLADOS in names:
            self.install_glados()
        piper = [n for n in names if n != voice_picker.GLADOS]
        if not piper:
            return
        self._dl_busy = True
        self.bot.log("Скачиваю голоса: " + ", ".join(piper))
        py = Path(sys.executable)
        if py.name.lower() == "pythonw.exe" and py.with_name("python.exe").exists():
            py = py.with_name("python.exe")   # консольный python, окна не будет из-за CREATE_NO_WINDOW

        def work():
            import subprocess
            p = subprocess.Popen([str(py), "-X", "utf8", str(core.BASE / "install_voices.py"), str(core.VOICES_DIR)] + piper,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(core.BASE),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self.bot.log(line[:140])
            return p.wait()

        def done(rc, err):
            self._dl_busy = False
            self.refresh_voices()
            if err or rc:
                messagebox.showerror("Голоса", "Скачать получилось не всё — подробности в журнале на «Главной».")
            else:
                messagebox.showinfo("Голоса", "Готово: " + ", ".join(piper) + ". В чате: !tts " + piper[0].lower())

        self.run_bg(work, done)

    def glados_done(self, ok):
        self.refresh_voices()
        if ok:
            self.bot.preload_engines()
            messagebox.showinfo("GLaDOS", "Голос GLaDOS установлен. В чате: !tts glados")
        elif self.bot.glados.state != "need_python":
            messagebox.showerror("GLaDOS", "Установить не получилось: " + (self.bot.glados.step or "см. журнал") +
                                 "\nПодробности: data\\glados_install.log. Повторить — кнопка «Установить GLaDOS».")

    def update_engine_status(self):
        g = self.bot.glados
        installed = self._glados_installed
        btn_text = None
        if g.state == "installing":
            text, color = f"GLaDOS: устанавливается — {g.step}", C["warn"]
        elif g.state == "need_python":
            text, color, btn_text = "GLaDOS: нужен Python 3.12 (его можно поставить автоматически)", C["warn"], "Поставить Python и GLaDOS"
            if not self._asked_python:
                self._asked_python = True
                if messagebox.askyesno("GLaDOS", "Для голоса GLaDOS нужен Python 3.12.\nУстановить его автоматически (через winget)?"):
                    g.start(allow_winget=True, on_done=lambda ok: self.ui_q.put(lambda: self.glados_done(ok)))
        elif installed:
            text, color = "GLaDOS: установлена ✓", C["ok"]
        else:
            text, color, btn_text = "GLaDOS: не установлена" + (f" ({g.step})" if g.state == "failed" and g.step else ""), C["warn"], "Установить GLaDOS"
        if g.state != "need_python":
            self._asked_python = False
        self.glados_lbl.configure(text=text, foreground=color)
        if btn_text and g.state != "installing":
            self.btn_glados.configure(text=btn_text)
            if not self.btn_glados.winfo_ismapped():
                self.btn_glados.pack(side="left", padx=8)
        elif self.btn_glados.winfo_ismapped():
            self.btn_glados.pack_forget()
        self.accent_lbl.configure(text=self.bot.accents.status())

    # ---------- вкладка «Настройки» ----------
    def build_settings(self, nb):
        f = ttk.Frame(nb, padding=(0, 12, 0, 0))
        nb.add(f, text="Настройки")
        f.columnconfigure(1, weight=1)
        c = self.cfg

        self.v_token = tk.StringVar(value=c.get("oauth_token", ""))
        self.v_chan = tk.StringVar(value=c.get("channel", ""))
        self.v_voice = tk.StringVar(value=c.get("default_voice", ""))
        self.v_dev = tk.StringVar(value=c.get("audio_device") or DEFAULT_DEVICE)
        self.v_maxc = tk.StringVar(value=str(c.get("max_chars", 200)))
        self.v_cd = tk.StringVar(value=str(c.get("user_cooldown_sec", 5)))
        self.v_q = tk.StringVar(value=str(c.get("max_queue", 15)))
        self.v_name = tk.BooleanVar(value=bool(c.get("say_name", False)))
        self.v_auto = tk.BooleanVar(value=bool(c.get("autoconnect", True)))
        self.v_acc = tk.BooleanVar(value=bool(c.get("accent_on", True)))
        self.v_accm = tk.StringVar(value=c.get("accent_model", "tiny2"))

        def row(r, label, widget):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="ew", pady=4)

        tok = ttk.Frame(f)
        tok.columnconfigure(0, weight=1)
        ttk.Entry(tok, textvariable=self.v_token, show="•").grid(row=0, column=0, sticky="ew")
        ttk.Button(tok, text="Войти через Twitch…", command=self.twitch_login_wizard).grid(row=0, column=1, padx=(6, 0))
        row(0, "Токен Twitch", tok)
        row(1, "Канал", ttk.Entry(f, textvariable=self.v_chan))
        self.v_voice_combo = ttk.Combobox(f, textvariable=self.v_voice, values=self.bot.voices.names())
        row(2, "Голос по умолчанию", self.v_voice_combo)
        self.dev_combo = ttk.Combobox(f, textvariable=self.v_dev, state="readonly",
                                      values=[DEFAULT_DEVICE] + core.list_output_devices())
        row(3, "Устройство вывода звука", self.dev_combo)
        row(4, "Макс. длина сообщения", ttk.Entry(f, textvariable=self.v_maxc, width=8))
        row(5, "Пауза на зрителя, сек", ttk.Entry(f, textvariable=self.v_cd, width=8))
        row(6, "Макс. очередь", ttk.Entry(f, textvariable=self.v_q, width=8))
        ttk.Checkbutton(f, text="Читать ник перед сообщением", variable=self.v_name).grid(
            row=7, column=1, sticky="w", pady=2)
        ttk.Checkbutton(f, text="Подключаться к чату при запуске", variable=self.v_auto).grid(
            row=8, column=1, sticky="w", pady=2)

        acc = ttk.Frame(f)
        ttk.Checkbutton(acc, text="Ставить ударения (RUAccent) в голосах Piper", variable=self.v_acc).pack(side="left")
        ttk.Combobox(acc, textvariable=self.v_accm, values=ACCENT_MODELS, width=10).pack(side="left", padx=8)
        acc.grid(row=9, column=1, sticky="w", pady=2)

        b = ttk.Frame(f)
        b.grid(row=10, column=0, columnspan=2, sticky="w", pady=14)
        ttk.Button(b, text="Сохранить", style="Accent.TButton", command=self.save_settings).pack(side="left")
        ttk.Button(b, text="Проверить токен", command=self.check_token).pack(side="left", padx=8)
        ttk.Label(f, text="В поле токена можно вставить весь адрес после авторизации — "
                          "токен вырежется сам.",
                  style="Mut.TLabel", wraplength=680).grid(row=11, column=0, columnspan=2, sticky="w")

    def save_settings(self):
        try:
            new = {
                "oauth_token": core.extract_token(self.v_token.get()),
                "channel": core.extract_channel(self.v_chan.get()),
                "default_voice": self.v_voice.get().strip().lower(),
                "audio_device": None if self.v_dev.get() == DEFAULT_DEVICE else self.v_dev.get(),
                "max_chars": max(20, int(self.v_maxc.get())),
                "user_cooldown_sec": max(0, float(self.v_cd.get())),
                "max_queue": max(1, int(self.v_q.get())),
                "say_name": bool(self.v_name.get()),
                "autoconnect": bool(self.v_auto.get()),
                "accent_on": bool(self.v_acc.get()),
                "accent_model": self.v_accm.get().strip() or "tiny2",
            }
        except ValueError:
            messagebox.showerror("Настройки", "Проверь числовые поля.")
            return
        was = self.bot.running()
        if was:
            self.bot.stop()
        self.bot.apply_cfg(new)
        self.v_token.set(new["oauth_token"])
        self.v_chan.set(new["channel"])
        self.refresh_voices()
        if was:
            self.connect()
        messagebox.showinfo("Настройки", "Сохранено.")

    # ---------- мастер входа в Twitch: напрямую (основной) или через twitchtokengenerator.com (запасной) ----------
    def twitch_login_wizard(self):
        """Три шага: ссылка -> разрешить доступ в браузере -> токен сам попадает в приложение."""
        top = tk.Toplevel(self.root)
        top.title("Вход в Twitch")
        top.configure(bg=C["bg"])
        top.transient(self.root)
        top.resizable(False, False)
        f = ttk.Frame(top, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        steps = [ttk.Label(f, text=t, font=("Segoe UI", 10)) for t in (
            "1.  Нажми «Войти через Twitch» — откроется браузер",
            "2.  В браузере войди в Twitch и нажми «Разрешить» (Activate / Authorize)",
            "3.  Вернись сюда — токен подставится сам")]
        for i, w in enumerate(steps):
            w.grid(row=i, column=0, sticky="w", pady=2)
        state = {"cancel": False, "busy": False}
        info = ttk.Label(f, text="Нужен аккаунт, под которым бот будет читать чат (обычно — твой).", style="Mut.TLabel", wraplength=460)
        info.grid(row=3, column=0, sticky="w", pady=(8, 4))
        link = tk.StringVar()
        link_row = ttk.Frame(f)
        link_row.grid(row=4, column=0, sticky="ew")
        link_row.columnconfigure(0, weight=1)
        ttk.Entry(link_row, textvariable=link, state="readonly").grid(row=0, column=0, sticky="ew")
        ttk.Button(link_row, text="Копировать ссылку", command=lambda: (self.root.clipboard_clear(), self.root.clipboard_append(link.get()))
                   ).grid(row=0, column=1, padx=(6, 0))
        bar = ttk.Progressbar(f, mode="indeterminate")
        bar.grid(row=5, column=0, sticky="ew", pady=(10, 4))
        msg = ttk.Label(f, text="", wraplength=460)
        msg.grid(row=6, column=0, sticky="w")

        def mark(active):
            for i, w in enumerate(steps):
                w.configure(foreground=C["ok"] if i < active else (C["fg"] if i == active else C["mut"]))

        def say(text, color=None):
            try:
                msg.configure(text=text, foreground=color or C["fg"])
            except tk.TclError:
                pass  # окно уже закрыто

        mark(0)

        def start(method):
            state["busy"], state["cancel"], state["method"] = True, False, method
            btn.configure(state="disabled")
            btn_old.configure(state="disabled")
            bar.start(12)
            say("Готовлю ссылку…")

            def on_url(url, code=""):
                def ui():
                    link.set(url)
                    mark(1)
                    say("Браузер открыт. Если не открылся — скопируй ссылку и вставь в браузер. "
                        + (f"Код для проверки: {code}. " if code else "") + "Жду разрешения…")
                self.ui_q.put(ui)
                webbrowser.open(url)

            def work():
                if method == "twitch":
                    res = twitch_auth.run_device_flow(on_url, None, lambda: state["cancel"])
                else:
                    res = twitch_auth.run_flow(on_url, lambda m: None, lambda: state["cancel"])
                self.ui_q.put(lambda: (mark(2), say("Токен получен, проверяю у Twitch…")))
                return res, twitch_auth.validate(res["token"])

            self.run_bg(work, done)

        def done(res, err):
            state["busy"] = False
            if state["cancel"]:
                return
            bar.stop()
            if err:
                btn.configure(state="normal")
                btn_old.configure(state="normal")
                mark(0)
                say("Не получилось: " + str(err), C["bad"])
                return
            tokens, check = res
            scopes = set(check.get("scopes", []))
            login = check.get("login", "")
            new = {"oauth_token": tokens["token"], "refresh_token": tokens["refresh"], "auth_method": state["method"]}
            if not self.v_chan.get().strip():
                new["channel"] = login
            was = self.bot.running()
            if was:
                self.bot.stop()
            self.bot.apply_cfg(new)
            self.v_token.set(self.cfg["oauth_token"])
            self.v_chan.set(self.cfg.get("channel", ""))
            if was:
                self.connect()
            mark(3)
            lines = [f"Готово! Аккаунт: {login}."]
            lack = [s for s in ("chat:read", "chat:edit") if s not in scopes]
            if lack:
                lines.append("Не хватает прав: " + ", ".join(lack) + ". Пройди вход ещё раз.")
            if "channel:manage:redemptions" not in scopes:
                lines.append("Нет права менять награды — цену/награду бот менять не сможет.")
            if self.cfg.get("channel") and self.cfg["channel"].lower() != login.lower():
                lines.append(f"Канал в настройках — {self.cfg['channel']}, а вошёл {login}: награды бот сможет менять только на своём канале.")
            say("\n".join(lines), C["ok"] if not lack else C["warn"])
            btn.configure(state="normal", text="Готово", command=top.destroy)
            btn_old.pack_forget()

        def cancel():
            state["cancel"] = True
            top.destroy()

        bt = ttk.Frame(f)
        bt.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        btn_old = ttk.Button(bt, text="Старый способ (twitchtokengenerator)", command=lambda: start("ttg"))
        btn_old.pack(side="left")
        ttk.Button(bt, text="Закрыть", command=cancel).pack(side="right")
        btn = ttk.Button(bt, text="Войти через Twitch", style="Accent.TButton", command=lambda: start("twitch"))
        btn.pack(side="right", padx=6)
        ttk.Label(f, text="«Войти через Twitch» — ключ выдаёт сам Twitch. Старый способ — через сайт "
                          "twitchtokengenerator.com, если с основным что-то не так.",
                  style="Mut.TLabel", wraplength=460).grid(row=8, column=0, sticky="w", pady=(8, 0))
        top.protocol("WM_DELETE_WINDOW", cancel)
        top.grab_set()

    def check_token(self):
        tok = self.v_token.get()
        self.run_bg(lambda: self.bot.check_token(tok), self.show_check)

    def show_check(self, result, err):
        if err:
            messagebox.showerror("Проверка токена", str(err))
        else:
            messagebox.showinfo("Проверка токена", result)

    # ---------- служебное ----------
    def run_bg(self, fn, done):
        def work():
            try:
                r = fn()
                self.ui_q.put(lambda: done(r, None))
            except Exception as e:
                self.ui_q.put(lambda e=e: done(None, e))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        while True:
            try:
                self.ui_q.get_nowait()()
            except queue.Empty:
                break
        # тяжёлое (поиск пакета GLaDOS на диске) — раз в 1,5 с, лёгкое — раз в 0,5 с
        if self._tick % 3 == 0:
            self._glados_installed = glados_setup.engine_installed(core.BASE)
            self.update_engine_status()
            self.update_ready()
        self._tick += 1
        text, color = STATUS.get(self.bot.status, STATUS["stopped"])
        self.status_lbl.configure(text=text)
        self.dot.itemconfigure(self.dot_id, fill=color)
        self.chan_lbl.configure(text=("#" + self.bot.chan) if self.bot.chan else "")
        p = self.bot.player
        now = (f"▶ {p.current}" if p.current else "Тишина") + f"  ·  в очереди: {p.q.qsize()}"
        if not self.bot.enabled:
            now = "TTS выключен в панели  ·  " + now
        self.now_lbl.configure(text=now)
        self.btn_conn.configure(text="Остановить" if self.bot.running() else "Подключиться")
        logs = self.bot.logs
        key = (len(logs), logs[-1] if logs else None)   # журнал перерисовываем, только если пришла новая строка
        if key != self.last_log:
            self.last_log = key
            self.log_txt.configure(state="normal")
            self.log_txt.delete("1.0", "end")
            self.log_txt.insert("end", "\n".join(logs))
            self.log_txt.see("end")
            self.log_txt.configure(state="disabled")
        self.root.after(500, self.poll)

    def on_close(self):
        try:
            self.bot.stop()
            self.bot.tera.kill()
            self.server.shutdown()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        TTSWindow().run()
    except Exception:
        err = traceback.format_exc()
        try:
            (core.BASE / "error.log").write_text(err, encoding="utf-8")
        except Exception:
            pass
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("Twitch TTS — ошибка запуска", err[-1500:])
        except Exception:
            print(err, file=sys.stderr)


if __name__ == "__main__":
    main()
