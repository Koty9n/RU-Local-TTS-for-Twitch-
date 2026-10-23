"""Ядро Twitch TTS: IRC (asyncio) + Piper (ONNX) + sounddevice.

Не зависит от GUI: им управляют окно (tts_app.py) и веб-панель для OBS (panel_server.py).
"""
import asyncio
import json
import os
import queue
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import OrderedDict, deque
from pathlib import Path

import accent
import glados_setup
import ort_tune
import replacements
import sounds
import twitch_auth


def app_dir():
    """Папка рядом с .exe (или со скриптом) — здесь лежат config.json, data/, voices/."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE = app_dir()
DATA = BASE / "data"
GITHUB = "https://github.com/Koty9n/RU-Local-TTS-for-Twitch-"   # страница проекта (то же в ui_theme.py)
VOICES_DIR = BASE / "voices"
CONFIG_PATH = BASE / "config.json"
DATA.mkdir(exist_ok=True)
VOICES_DIR.mkdir(exist_ok=True)


class BotError(Exception):
    pass


class TokenRejected(BotError):
    """Twitch ответил 401: токен просрочен или неверный."""


# ───────────────────────── файлы и конфиг ─────────────────────────
def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


ALLOWED_FILE = "allowed_users.txt"
BLOCKED_FILE = "blocked_users.txt"
MUTE_DEFAULT_MIN = 10
MUTE_MAX_MIN = 7 * 24 * 60


def parse_nicks(src):
    """Ники из строки/списка: разделители — пробел, запятая, ; и перенос строки; '#' — комментарий до конца строки."""
    if isinstance(src, (list, tuple, set)):
        src = "\n".join(str(x) for x in src)
    out = []
    for line in str(src or "").splitlines():
        line = line.split("#", 1)[0]
        for w in re.split(r"[\s,;]+", line):
            w = w.strip().lstrip("@").lower()
            if w and re.fullmatch(r"\w{1,40}", w) and w not in out:
                out.append(w)
    return out


def _mtime(path):
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return 0


DEFAULT_CFG = {
    "oauth_token": "",
    "refresh_token": "",       # выдаёт мастер входа; нужен для автообновления токена
    "auth_method": "",         # twitch — вход напрямую через Twitch; ttg (или пусто) — через twitchtokengenerator.com
    "channel": "",
    "default_voice": "glados",
    "audio_device": None,      # имя устройства вывода или null (по умолчанию)
    "volume": 100,
    "max_chars": 200,
    "user_cooldown_sec": 5,
    "max_queue": 15,
    "say_name": False,
    "dup_window_sec": 30,      # одинаковое сообщение (от кого угодно) за это время читается один раз; 0 — выключить
    "voice_cache": 4,          # сколько голосов Piper держать в памяти (~40 МБ каждый): меньше — смена голоса грузит заново
    "autoconnect": True,
    "panel_port": 8765,
    "panel_key": "",
    "aliases": {},
    # русская GLaDOS через движок TeraTTS (ставит install.ps1 или кнопка «Установить GLaDOS»)
    "tera_voices": {
        "glados": {"model": "TeraTTS/glados2-g2p-vits", "length_scale": 1.1},
    },
    "tera_accent": "tiny2",    # модель ударений ruaccent: tiny2 — самая быстрая; при сбое воркер сам подберёт другую
    "tera_r_fix": "off",       # off | double — удвоение «р» у GLaDOS, если звучит слабо (проверка: test_glados.bat)
    "tera_unload_min": 0,      # выгружать движок из памяти после N минут простоя (0 = держать, ответ без задержки)
    "tera_preload": True,      # загружать движок сразу при подключении к чату
    "tera_python": "",         # путь к python.exe окружения TeraTTS (по умолчанию venv программы)
    # эффект-голоса поверх голосов Piper (нужен хотя бы один голос Piper). Пример:
    # "fx_voices": {"robot": {"base": "мойголос", "fx": {"pitch": 1.06, "ring_hz": 70, "ring_mix": 0.28,
    #               "echo_ms": 11, "echo_fb": 0.35, "crush_bits": 0, "drive": 1.4}}}
    "fx_voices": {},
    # ударения для голосов Piper (RUAccent). GLaDOS ставит ударения сама (tera_accent).
    "accent_on": True,
    "accent_model": "tiny2",   # tiny2 — лёгкая и быстрая; точнее, но тяжелее: turbo3.1
    "accent_mark": "auto",     # auto | combining | upper | plus | phoneme | off — как передать ударение в Piper
    "glados_autoinstall": True,   # при первом запуске доставить GLaDOS самому, если установщик её не поставил
    "glados_install_tried": False,
    "accent_dictionary": True, # false — только нейросеть, без словаря: меньше памяти, чуть хуже качество
    # лёгкие ударения (Piper и GLaDOS): ruaccent tiny_mode, GLaDOS без своего словаря — ~1 ГБ ОЗУ вместо ~4 ГБ.
    # false — прежний тяжёлый режим (меняется после перезапуска программы)
    "accent_light": True,
    # нагрузка на процессор: сколько ядер берёт каждая нейросеть (0 — все, как раньше; 2 — ещё легче, но медленнее)
    # и пониженный приоритет, чтобы игра и OBS получали процессор первыми (меняется после перезапуска программы)
    "cpu_threads": 3,
    "low_priority": True,
    # словарь замен перед озвучкой: data/replacements.txt (свой) + data/replacements_*.txt (готовые)
    "replace_on": True,
    "replace_strip_emoji": True,  # эмодзи, которых нет в словаре, — убирать (движки их не читают)
    # звуки вместо слов (в словаре «kekw = [смех]», файлы data/sounds/*.wav); всё правится в панели OBS
    "sounds_on": True,
    "sound_max_per_msg": 3,    # больше звуков в одном сообщении не играет (лишние выкидываются)
    "sound_max_sec": 3,        # длиннее — обрезается с затуханием
    "sound_volume": 80,        # % от громкости голоса (общий ползунок громкости тоже действует)
}


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    cfg.update(load_json(CONFIG_PATH, {}))
    changed = False
    if not cfg.get("panel_key"):
        cfg["panel_key"] = secrets.token_urlsafe(12)
        changed = True
    if int(cfg.get("cfg_rev", 0) or 0) < 1:   # 23.10.2026: старый умолчательный voice_cache 2 -> 4 (своё число не трогаем)
        if cfg.get("voice_cache") == 2:
            cfg["voice_cache"] = 4
        cfg["cfg_rev"] = 1
        changed = True
    if changed:
        save_json(CONFIG_PATH, cfg)
    return cfg


def save_cfg(cfg):
    save_json(CONFIG_PATH, cfg)


def extract_token(s):
    """Принимает голый токен, «oauth:...» или весь адрес после авторизации (…#access_token=...&scope=...)."""
    s = (s or "").strip().strip("\"'")
    if "access_token=" in s:
        s = s.split("access_token=", 1)[1].split("&", 1)[0]
    s = s.replace("oauth:", "").strip()
    # токен Twitch — латиница и цифры; заглушка вроде «ВСТАВЬ_ТОКЕН» из старого config.example.json — не токен
    return s if re.fullmatch(r"[A-Za-z0-9_\-]{10,200}", s) else ""


def extract_channel(s):
    s = (s or "").strip().lower().rstrip("/")
    if "twitch.tv/" in s:
        s = s.split("twitch.tv/", 1)[1].split("/", 1)[0]
    s = s.lstrip("#@").strip()
    return s if re.fullmatch(r"[a-z0-9_]{1,25}", s) else ""   # ник Twitch; «твой_канал» — заглушка


# ───────────────────────── текст ─────────────────────────
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)


def strip_emotes(text, emotes_tag):
    """Убирает смайлы Twitch (чтобы TTS не читал «Kappa»)."""
    if not emotes_tag:
        return text
    chars = list(text)
    for part in emotes_tag.split("/"):
        _, _, ranges = part.partition(":")
        for r in ranges.split(","):
            a, _, b = r.partition("-")
            if a.isdigit() and b.isdigit():
                for i in range(int(a), min(int(b) + 1, len(chars))):
                    chars[i] = " "
    return "".join(chars)


def clean(text, max_chars):
    text = URL_RE.sub(" ", text)
    text = re.sub(r"(.)\1{3,}", r"\1\1\1", text)
    text = re.sub(r"(\w{2,3}?)\1{3,}", r"\1\1\1", text)    # «ахахахахаха» -> «ахахаха»
    text = re.sub(r"(?i)\b(\w+)((?:[\s,.!?]+\1\b){2})(?:[\s,.!?]+\1\b)+", r"\1\2", text)   # «лол лол лол лол» -> три раза
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# ───────────────────────── чёрный список ─────────────────────────
LOOK = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м", "o": "о",
    "p": "р", "t": "т", "x": "х", "y": "у", "0": "о", "3": "з", "4": "ч", "6": "б",
    "@": "а", "$": "с",
})


def _variants(text):
    base = text.lower().replace("ё", "е")
    return [base, base.translate(LOOK)]


def _collapse(s):
    return re.sub(r"(.)\1+", r"\1", s)


def _norm_word(line):
    return _collapse(re.sub(r"[\W_]+", "", line.lower().replace("ё", "е")))


class Blacklist:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text("# одно слово/фраза на строку; строки с # игнорируются\n", encoding="utf-8")
        self.load()

    def _files(self):
        """Основной blacklist.txt + любые готовые списки data/blacklist_*.txt (например blacklist_twitch.txt)."""
        extra = sorted(p for p in self.path.parent.glob("blacklist_*.txt") if p != self.path)
        return [self.path] + extra

    def _stamp(self):
        out = []
        for f in self._files():
            try:
                out.append((f.name, f.stat().st_mtime_ns))
            except OSError:
                pass
        return out

    def load(self):
        """raw — слова из blacklist.txt (их показывает панель и можно удалять); words — все слова из всех файлов."""
        self.raw, self.words, self.phrases, self.domains = [], [], [], []
        self.min_len = {}   # короткое слово -> длина без сжатия повторов: «www» не должно ловить «w»
        for f in self._files():
            try:
                lines = f.read_text(encoding="utf-8-sig").splitlines()
            except OSError:
                continue
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#"):
                    w = _norm_word(line)
                    if w:
                        if f == self.path:
                            self.raw.append(line)
                        if line.startswith(".") and re.fullmatch(r"\.[\w.]+", line):  # «.gg» — окончание адреса сайта
                            if line.lower() not in self.domains:
                                self.domains.append(line.lower())
                            continue
                        bucket = self.phrases if len(re.findall(r"[^\W_]+", line)) > 1 else self.words
                        if w not in bucket:
                            bucket.append(w)
                        n = len(re.sub(r"[\W_]+", "", line))
                        self.min_len[w] = min(n, self.min_len.get(w, n))
        self._seen = self._stamp()

    def hit(self, text):
        if self._stamp() != self._seen:  # файл списка правили руками — подхватываем без перезапуска
            self.load()
        low = text.lower()
        if any(re.search(r"\w" + re.escape(d) + r"\b", low) for d in self.domains):
            return True
        for v in _variants(text):
            toks = re.findall(r"[^\W_]+", v)
            tokens = {_collapse(t) for t in toks}
            # короткие слова целиком: «хууй» = «хуй», но «ww» ≠ «www» (слово короче, чем в списке)
            short = {_collapse(t) for t in toks if len(t) >= self.min_len.get(_collapse(t), 0)}
            # куски для поиска подстрокой: каждое слово и буквы, написанные врозь («с у к а», «с.у.к.а»);
            # соседние слова не склеиваем — иначе «вас у калитки» ловится как «сука»
            pieces, run = set(tokens), []
            for t in toks + [""]:
                if len(t) == 1:
                    run.append(t)
                    continue
                if len(run) > 1:
                    pieces.add(_collapse("".join(run)))
                run = []
            for w in self.words:
                # длинные слова — подстрокой (ловит «хууй», «нахуй»), короткие — только целиком
                if (len(w) >= 4 and any(w in p for p in pieces)) or w in short:
                    return True
            if self.phrases:
                squash = _collapse(re.sub(r"[\W_]+", "", v))
                if any(p in squash for p in self.phrases):  # фразы — по склеенному тексту, как раньше
                    return True
        return False

    def add(self, word):
        word = word.strip()
        if word and word.lower() not in [r.lower() for r in self.raw]:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(word + "\n")
            self.load()

    def remove(self, word):
        norm = word.strip().lower()
        lines = [l for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip().lower() != norm]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.load()


# ───────────────────────── движок TeraTTS (отдельный процесс) ─────────────────────────
TERA_WORKER = BASE / "tera_worker.py"


def tera_python(cfg):
    custom = (cfg.get("tera_python") or "").strip()
    if custom:
        return Path(custom)
    return glados_setup.engine_python(BASE)   # общий venv, а у старых установок — venv_tera


def tera_available(cfg):
    py = tera_python(cfg)
    ok = bool(py and Path(py).exists() and TERA_WORKER.exists())
    if ok and not (cfg.get("tera_python") or "").strip():   # своё окружение пользователя не проверяем, наше — да
        ok = glados_setup.engine_installed(BASE)
    return ok


class TeraClient:
    """Держит воркер с TeraTTS+ruaccent в отдельном процессе; отдаёт звук по предложениям."""

    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log
        self.proc = None
        self.model = None
        self.lock = threading.Lock()
        self.last_used = time.time()
        threading.Thread(target=self._idle_loop, daemon=True).start()

    def alive(self):
        return bool(self.proc and self.proc.poll() is None)

    def kill(self):
        proc, self.proc = self.proc, None
        if proc:
            try:
                proc.kill()
                proc.wait(3)
            except Exception:
                pass

    def _idle_loop(self):
        while True:
            time.sleep(15)
            idle = float(self.cfg.get("tera_unload_min", 0) or 0) * 60
            if idle and self.alive() and time.time() - self.last_used > idle and self.lock.acquire(False):
                try:
                    self.kill()
                    self.log("Движок GLaDOS выгружен из памяти (простой)")
                finally:
                    self.lock.release()

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.proc.stdout.read(n - len(buf))
            if not chunk:
                raise RuntimeError("воркер TeraTTS неожиданно завершился (см. data/tera_worker.log)")
            buf += chunk
        return buf

    def _read_header(self):
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("воркер TeraTTS неожиданно завершился (см. data/tera_worker.log)")
        return json.loads(line.decode("utf-8", "replace"))

    def _watchdog(self, seconds):
        proc = self.proc
        t = threading.Timer(seconds, lambda: proc.kill() if proc and proc.poll() is None else None)
        t.daemon = True
        t.start()
        return t

    def _start(self, model, accent):
        py = tera_python(self.cfg)
        if not py or not TERA_WORKER.exists():
            raise RuntimeError("Движок GLaDOS не установлен: вкладка «Голоса» → «Установить GLaDOS»")
        wdir = DATA / "tera"
        wdir.mkdir(exist_ok=True)
        errlog = open(DATA / "tera_worker.log", "ab")
        self.log("Загружаю движок GLaDOS…")
        self.proc = subprocess.Popen(
            [str(py), "-X", "utf8", str(TERA_WORKER), model, accent],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog, cwd=str(wdir),
            env={**os.environ, "TTS_R_FIX": str(self.cfg.get("tera_r_fix", "off")), "PYTHONUTF8": "1",
                 "TTS_ACCENT_LIGHT": "1" if self.cfg.get("accent_light", True) else "0",
                 "TTS_CPU_THREADS": str(int(self.cfg.get("cpu_threads", 3) or 0)),
                 "TTS_LOW_PRIORITY": "1" if self.cfg.get("low_priority", True) else "0"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.model = model
        wd = self._watchdog(900)  # первая загрузка может качать модели
        try:
            head = self._read_header()
        finally:
            wd.cancel()
        if head.get("error"):
            self.kill()
            raise RuntimeError(head["error"])
        acc = head.get("accent")
        self.log("Движок GLaDOS готов" + (f" (ударения: {acc})" if acc else " (БЕЗ ударений — см. data/tera_worker.log)"))

    def preload(self, model="TeraTTS/glados2-g2p-vits"):
        """Фоновая загрузка, чтобы первая фраза не ждала."""
        def work():
            try:
                with self.lock:
                    if not self.alive():
                        self._start(model, self.cfg.get("tera_accent") or "tiny2")
                    self.last_used = time.time()
            except Exception as e:
                self.log(f"Не удалось загрузить движок GLaDOS: {e}")
        threading.Thread(target=work, daemon=True).start()

    def synth_stream(self, text, model="TeraTTS/glados2-g2p-vits", length_scale=1.1):
        """Генератор (частота, int16-байты): по одному куску на предложение. Закрытие генератора
        (пропуск !skip) дочитывает остаток, чтобы не терять загруженный движок."""
        with self.lock:
            if self.alive() and self.model != model:
                self.kill()
            if not self.alive():
                self._start(model, self.cfg.get("tera_accent") or "tiny2")
            self.last_used = time.time()
            wd = self._watchdog(240)
            finished = False
            try:
                req = json.dumps({"text": text, "ls": float(length_scale)}, ensure_ascii=False) + "\n"
                self.proc.stdin.write(req.encode("utf-8"))
                self.proc.stdin.flush()
                while True:
                    head = self._read_header()
                    if head.get("error"):
                        raise RuntimeError(head["error"])
                    n = int(head.get("n", 0))
                    pcm = self._read_exact(n) if n else b""
                    finished = not head.get("more", False)
                    yield int(head.get("rate", 22050)), pcm
                    if finished:
                        break
            except GeneratorExit:
                try:
                    while not finished:
                        head = self._read_header()
                        if head.get("error"):
                            break
                        n = int(head.get("n", 0))
                        if n:
                            self._read_exact(n)
                        finished = not head.get("more", False)
                except Exception:
                    self.kill()
                raise
            except Exception:
                self.kill()  # в следующий раз запустится заново
                raise
            finally:
                wd.cancel()
                self.last_used = time.time()

    def synth(self, text, model="TeraTTS/glados2-g2p-vits", length_scale=1.1):
        """Целиком: (частота, байты). Нужно для проверок; плеер использует synth_stream."""
        rate, parts = 22050, []
        for rate, pcm in self.synth_stream(text, model, length_scale):
            parts.append(pcm)
        return rate, b"".join(parts)


# ───────────────────────── голоса (Piper) ─────────────────────────
NAME_RE = re.compile(r"^[a-z]{2}_[A-Za-z]{2}-(.+)-(?:x_low|low|medium|high)$")


def suggest_voice_name(stem):
    m = NAME_RE.match(stem)
    return m.group(1) if m else stem


class Voices:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cache = OrderedDict()
        self.paths = {}
        self.scan()

    def scan(self):
        self.paths = {}
        for p in sorted(VOICES_DIR.glob("*.onnx")):
            if p.with_name(p.name + ".json").exists():
                self.paths[suggest_voice_name(p.stem).lower()] = p
        for alias, target in self.cfg.get("aliases", {}).items():
            if target.lower() in self.paths:
                self.paths[alias.lower()] = self.paths[target.lower()]
        (DATA / "voices.txt").write_text("\n".join(self.names()) + "\n", encoding="utf-8")  # для OBS

    def tera_defs(self):
        """Голоса движка TeraTTS — только если он установлен."""
        if not tera_available(self.cfg):
            return {}
        return {k.lower(): v for k, v in (self.cfg.get("tera_voices") or {}).items()}

    def is_tera(self, name):
        return (name or "").lower() in self.tera_defs() and (name or "").lower() not in self.paths

    def fx_defs(self):
        if not self.paths:  # эффект-голосам нужен базовый голос Piper; без Piper-голосов их нет
            return {}
        tera = self.tera_defs()
        out = {}
        for k, v in (self.cfg.get("fx_voices") or {}).items():
            k = k.lower()
            out[k + "-fx" if k in tera else k] = v  # настоящий движок занимает имя, эффект-версия получает «-fx»
        return out

    def exists(self, name):
        n = (name or "").lower()
        return n in self.paths or n in self.tera_defs() or n in self.fx_defs()

    def names(self):
        return sorted(set(self.paths) | set(self.tera_defs()) | set(self.fx_defs()))

    def resolve(self, name):
        """Имя -> (настоящий голос, параметры эффекта или None)."""
        n = name.lower()
        if n in self.paths:
            return n, None
        d = self.fx_defs().get(n)
        if d is None:
            raise KeyError(name)
        base = (d.get("base") or "").lower()
        if base not in self.paths:  # нужной базы нет — берём первый настоящий голос
            real = sorted(self.paths)
            if not real:
                raise KeyError("нет ни одного настоящего голоса для эффекта")
            base = real[0]
        return base, d.get("fx") or {}

    def get(self, name):
        path = self.paths[name]
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        from piper import PiperVoice  # ленивый импорт — быстрый старт окна
        kw = {}
        try:   # espeak-ng не читает данные по пути с русскими буквами — даём ему латинский путь
            import ascii_paths
            from piper.phonemize_espeak import ESPEAK_DATA_DIR
            kw["espeak_data_dir"] = ascii_paths.ascii_dir(ESPEAK_DATA_DIR)
        except Exception:
            pass
        voice = PiperVoice.load(str(path), **kw)
        self.cache[path] = voice
        while len(self.cache) > max(1, int(self.cfg.get("voice_cache", 2))):
            self.cache.popitem(last=False)  # выгружаем старейший — экономим ОЗУ
        return voice

    def add_files(self, onnx, config_json, name):
        """Копирует пару файлов Piper в voices/ под выбранным именем."""
        name = re.sub(r'[\\/:*?"<>|]+', "", name or "").strip()
        if not name:
            raise ValueError("Пустое имя голоса")
        if self.exists(name):
            raise ValueError(f"Голос «{name}» уже есть")
        meta = load_json(config_json, None)
        if not isinstance(meta, dict) or "phoneme_id_map" not in meta:
            raise ValueError("Это не похоже на файл настроек Piper (.onnx.json)")
        dst = VOICES_DIR / f"{name}.onnx"
        if dst.exists():
            raise ValueError("Файл с таким именем уже лежит в voices/")
        shutil.copy2(onnx, dst)
        shutil.copy2(config_json, dst.with_name(dst.name + ".json"))
        self.scan()
        return name.lower()

    def remove(self, name):
        if name.lower() in self.fx_defs() and name.lower() not in self.paths:
            fx = self.cfg.get("fx_voices") or {}
            for k in [k for k in fx if k.lower() == name.lower()]:
                fx.pop(k)
            save_cfg(self.cfg)
            self.scan()
            return
        path = self.paths.get(name.lower())
        if not path or path.parent.resolve() != VOICES_DIR.resolve():
            raise ValueError("Голос не найден")
        self.cache.pop(path, None)
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".json").unlink(missing_ok=True)
        self.scan()


def synth_chunks(voice, text, accents=None):
    """Речь Piper по предложениям (int16-байты). accents — PiperAccents: расставляет ударения (RUAccent)."""
    if accents is not None:
        text, plus = accents.prepare(voice, text)
        if plus:
            try:
                gen = accent.phoneme_chunks(voice, text, plus)
            except Exception as e:
                accents.log(f"Ударения (запасной режим) не сработали: {type(e).__name__}: {e}")
                gen = None
            if gen is not None:
                yield from gen
                return
    if hasattr(voice, "synthesize_stream_raw"):  # piper-tts < 1.3
        yield from voice.synthesize_stream_raw(text)
    else:
        for ch in voice.synthesize(text):
            yield ch.audio_int16_bytes


def list_output_devices():
    try:
        import sounddevice as sd
        ha = sd.default.hostapi
        return [d["name"] for d in sd.query_devices() if d["max_output_channels"] > 0 and d["hostapi"] == ha]
    except Exception:
        return []


def resolve_device(sd, name):
    if not name:
        return None
    devs = sd.query_devices()
    ha = sd.default.hostapi
    for strict in (True, False):
        for i, d in enumerate(devs):
            if d["max_output_channels"] > 0 and (d["hostapi"] == ha or not strict) and d["name"] == name:
                return i
    return None


class GladosFx:
    """Лёгкая обработка звука (только numpy): кольцевая модуляция + короткое эхо + мягкий клиппинг.
    Высота тона повышается проигрыванием на чуть большей частоте (pitch) — это ничего не стоит по CPU."""

    def __init__(self, rate, p):
        self.rate = rate
        self.pitch = max(0.5, min(1.5, float(p.get("pitch", 1.06))))
        self.ring_hz = float(p.get("ring_hz", 70))
        self.ring_mix = max(0.0, min(1.0, float(p.get("ring_mix", 0.28))))
        self.echo_n = max(1, int(rate * float(p.get("echo_ms", 11)) / 1000))
        self.echo_fb = max(0.0, min(0.9, float(p.get("echo_fb", 0.35))))
        self.bits = int(p.get("crush_bits", 0))
        self.drive = max(0.1, float(p.get("drive", 1.4)))
        self.t = 0
        self.hist = None

    def process(self, raw):
        import numpy as np
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        n = len(x)
        if n == 0:
            return raw
        if self.ring_mix > 0:
            t = (np.arange(n) + self.t) / (self.rate * self.pitch)
            mod = np.sin(2 * np.pi * self.ring_hz * t).astype(np.float32)
            x = x * (1 - self.ring_mix) + x * mod * self.ring_mix
        self.t += n
        if self.echo_fb > 0:
            D = self.echo_n
            if self.hist is None:
                self.hist = np.zeros(D, dtype=np.float32)
            y = np.empty_like(x)
            for i in range(0, n, D):
                blk = x[i:i + D]
                m = len(blk)
                yb = blk + self.echo_fb * self.hist[:m]
                y[i:i + m] = yb
                self.hist = yb if m == D else np.concatenate((self.hist[m:], yb))
            x = y
        if self.bits > 0:
            levels = 2.0 ** (self.bits - 1)
            x = np.round(x * levels) / levels
        x = np.tanh(x * self.drive) / np.tanh(self.drive)
        return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


def apply_volume(raw, vol):
    if abs(vol - 1.0) < 0.01:
        return raw
    import numpy as np
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) * vol
    return np.clip(a, -32768, 32767).astype(np.int16).tobytes()


class Player(threading.Thread):
    def __init__(self, voices, get_device, dropped, log, tera=None, accents=None):
        super().__init__(daemon=True)
        self.tera = tera
        self.accents = accents
        self.q = queue.Queue()
        self.voices = voices
        self.get_device = get_device
        self.dropped = dropped
        self.log = log
        self.skip = threading.Event()
        self.volume = 1.0
        self.current = ""
        self.current_id = None     # id сообщения Twitch, которое звучит сейчас (чтобы оборвать при удалении)
        self.sounds = None         # sounds.Sounds — ставит Bot

    def clear(self):
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def run(self):
        try:
            import sounddevice as sd
        except Exception as e:
            sd = None
            self.log(f"Звук недоступен (sounddevice): {e}")
        while True:
            voice_name, text, msg_id = self.q.get()
            self.skip.clear()
            if sd is None or (msg_id and msg_id in self.dropped):  # сообщение удалил модератор
                continue
            self.current = sounds.to_text(text)[:80]
            self.current_id = msg_id
            try:
                parts = self.sounds.split(text) if self.sounds else [("text", text)]
                for kind, part in parts:   # «текст / звук / текст» по очереди; «Пропустить» обрывает всё
                    if self.skip.is_set():
                        break
                    if kind == "sound":
                        self.play_sound(sd, part)
                    elif voice_name:
                        self.play_text(sd, voice_name, part)
            except Exception as e:
                self.log(f"Ошибка озвучки: {e}")
            finally:
                self.current = ""
                self.current_id = None

    def play_sound(self, sd, name):
        snd = self.sounds.get(name)
        if snd is None:
            return
        rate, pcm = snd
        with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16",
                                device=resolve_device(sd, self.get_device())) as stream:
            pcm = apply_volume(pcm, self.volume)
            for i in range(0, len(pcm), 4096):
                if self.skip.is_set():
                    break
                stream.write(pcm[i:i + 4096])

    def play_text(self, sd, voice_name, text):
        if self.voices.is_tera(voice_name):
            self.play_tera(sd, voice_name, text)
            return
        base, fx_params = self.voices.resolve(voice_name)
        voice = self.voices.get(base)
        rate = voice.config.sample_rate
        fx = GladosFx(rate, fx_params) if fx_params is not None else None
        device = resolve_device(sd, self.get_device())

        def open_stream(r):
            return sd.RawOutputStream(samplerate=r, channels=1, dtype="int16", device=device)

        try:
            stream_cm = open_stream(int(rate * fx.pitch) if fx else rate)
        except Exception:  # устройство не принимает «нестандартную» частоту — играем без повышения тона
            if fx:
                fx.pitch = 1.0
            stream_cm = open_stream(rate)
        with stream_cm as stream:
            for raw in synth_chunks(voice, text, self.accents):
                if fx:
                    raw = fx.process(raw)
                raw = apply_volume(raw, self.volume)
                for i in range(0, len(raw), 4096):
                    if self.skip.is_set():
                        break
                    stream.write(raw[i:i + 4096])
                if self.skip.is_set():
                    break

    def play_tera(self, sd, name, text):
        d = self.voices.tera_defs()[name.lower()]
        gen = self.tera.synth_stream(text, d.get("model", "TeraTTS/glados2-g2p-vits"), d.get("length_scale", 1.1))
        stream = None
        try:
            for rate, pcm in gen:  # звук приходит по предложениям: первое играет, пока считается следующее
                if self.skip.is_set():
                    break
                if not pcm:
                    continue
                if stream is None:
                    stream = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16",
                                                device=resolve_device(sd, self.get_device()))
                    stream.start()
                for i in range(0, len(pcm), 8192):
                    if self.skip.is_set():
                        break
                    stream.write(apply_volume(pcm[i:i + 8192], self.volume))
        finally:
            gen.close()
            if stream is not None:
                try:
                    stream.abort() if self.skip.is_set() else stream.stop()
                finally:
                    stream.close()


# ───────────────────────── бот ─────────────────────────
ADMIN_SUBS = {"add", "del", "remove", "set", "list", "ban", "unban", "block", "unblock",
              "price", "reward", "reload"}


def parse_irc(line):
    tags = {}
    if line.startswith("@"):
        raw, _, line = line.partition(" ")
        for kv in raw[1:].split(";"):
            k, _, v = kv.partition("=")
            tags[k] = v
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
    cmd, _, rest = line.partition(" ")
    return tags, prefix, cmd, rest


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        ort_tune.apply(cfg.get("cpu_threads", 3), cfg.get("low_priority", True))   # до загрузки любых моделей
        self.logs = deque(maxlen=200)
        self.state = load_json(DATA / "state.json", {"allowed": [], "reward_id": "", "price": 0})
        self.state.setdefault("allowed", [])
        self.state.setdefault("muted", {})
        self._sync_lock = threading.RLock()
        self._allowed_path = DATA / ALLOWED_FILE
        self._state_path = DATA / "state.json"
        self._init_allowed()
        self._blocked_path = DATA / BLOCKED_FILE
        self.blocked, self._m_blocked = [], None
        if not self._blocked_path.exists():
            self._write_blocked_file()
        self.sync_blocked()
        self.user_voices = load_json(DATA / "user_voices.json", {})
        self.bl = Blacklist(DATA / "blacklist.txt")
        self.repl = replacements.Replacements(DATA / "replacements.txt", self.log)
        self.voices = Voices(cfg)
        if self.voices.names() and not self.voices.exists(cfg.get("default_voice")):
            self.cfg["default_voice"] = self.voices.names()[0]
        self.dropped = set()
        self.recent_ids = {}       # ник -> id его сообщений в очереди (для бана/таймаута)
        self.tera = TeraClient(cfg, self.log)
        self.accents = accent.PiperAccents(cfg, DATA / "ruaccent", self.log)
        self.glados = glados_setup.GladosInstaller(BASE, DATA, self.log, accent=cfg.get("tera_accent") or "tiny2")
        self.player = Player(self.voices, lambda: self.cfg.get("audio_device"), self.dropped, self.log, self.tera, self.accents)
        self.player.volume = max(0.0, min(2.0, float(cfg.get("volume", 100)) / 100))
        self.sounds = self.player.sounds = sounds.Sounds(DATA / "sounds", self.cfg, self.log)
        self.player.start()
        self.enabled = True
        self.status = "stopped"
        self.last_use = {}
        self.recent_texts = {}     # текст без знаков/регистра -> когда читали (одинаковое сообщение подряд — один раз)
        self.writer = None
        self.nick = self.client_id = self.user_id = ""
        self.can_manage = False
        self.thread = None
        self.loop = None
        self.task = None

    # ---- свойства конфига ----
    @property
    def token(self):
        return extract_token(self.cfg.get("oauth_token", ""))

    @property
    def chan(self):
        return extract_channel(self.cfg.get("channel", ""))

    def log(self, msg):
        self.logs.append(time.strftime("%H:%M:%S ") + str(msg))

    def apply_cfg(self, new):
        if extract_token(new.get("oauth_token", "")) != self.token:
            self.client_id = ""  # токен сменился — переавторизация
            if "refresh_token" not in new:
                self.cfg["refresh_token"] = ""  # вставлен вручную другой токен — старый refresh к нему не подходит
        self.cfg.update(new)
        self.cfg["oauth_token"] = extract_token(self.cfg.get("oauth_token", ""))
        self.cfg["channel"] = extract_channel(self.cfg.get("channel", ""))
        self.player.volume = max(0.0, min(2.0, float(self.cfg.get("volume", 100)) / 100))
        self.voices.scan()
        save_cfg(self.cfg)

    def preload_engines(self):
        """Вызывается при запуске программы: движки грузятся в фоне, а не при первой фразе."""
        if self.cfg.get("tera_preload", True) and self.voices.tera_defs():
            d = next(iter(self.voices.tera_defs().values()))
            self.tera.preload(d.get("model", "TeraTTS/glados2-g2p-vits"))
        self.accents.preload(lambda: bool(self.voices.paths))

    def ensure_glados(self, on_done=None):
        """Первый запуск: GLaDOS ещё не установлена — ставим сами (один раз; дальше — кнопкой на вкладке «Голоса»)."""
        if tera_available(self.cfg) or not self.cfg.get("glados_autoinstall", True) or self.cfg.get("glados_install_tried"):
            return False
        try:   # при установке GLaDOS не выбрали (data/voices.choice) — сами не ставим, только кнопкой
            chosen = (DATA / "voices.choice").read_text(encoding="utf-8-sig").split()
            if "GLaDOS" not in chosen:
                return False
        except OSError:
            pass
        self.cfg["glados_install_tried"] = True
        save_cfg(self.cfg)
        self.glados.start(on_done=on_done)
        return True

    def save_state(self):
        with self._sync_lock:
            save_json(self._state_path, self.state)
            self._m_state = _mtime(self._state_path)

    # ---- список разрешённых: data/allowed_users.txt <-> state.json <-> панель ----
    def _write_allowed_file(self):
        head = ("# Кому разрешено озвучивать через !!!  (модеры, владелец и VIP — всегда)\n"
                "# Ники через пробел, запятую или с новой строки. '#' — комментарий.\n"
                "# Файл можно править пока бот запущен — изменения подхватятся сами (~1-2 сек).\n")
        body = "\n".join(self.state["allowed"])
        self._allowed_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._allowed_path.with_suffix(".tmp")
        tmp.write_text(head + body + "\n", encoding="utf-8")
        tmp.replace(self._allowed_path)
        self._m_allowed = _mtime(self._allowed_path)

    def _init_allowed(self):
        with self._sync_lock:
            from_state = parse_nicks(self.state.get("allowed"))
            if self._allowed_path.exists():
                from_file = parse_nicks(self._allowed_path.read_text(encoding="utf-8", errors="replace"))
                merged = list(from_file)
                for n in from_state:          # миграция: то, что было только в state.json, не теряем
                    if n not in merged:
                        merged.append(n)
            else:
                merged = from_state
            self.state["allowed"] = merged
            self._write_allowed_file()
            self.save_state()

    def sync_allowed(self):
        """Подхватывает ручные правки data/allowed_users.txt и data/state.json (что изменилось последним — то и верно)."""
        with self._sync_lock:
            ma, ms = _mtime(self._allowed_path), _mtime(self._state_path)
            ca, cs = ma != self._m_allowed, ms != self._m_state
            if not (ca or cs):
                return
            try:
                if ca and (not cs or ma >= ms):
                    new = parse_nicks(self._allowed_path.read_text(encoding="utf-8", errors="replace"))
                    self.state["allowed"] = new
                    self.save_state()
                    self.log("Список разрешённых обновлён из allowed_users.txt")
                elif cs:
                    raw = json.loads(self._state_path.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        raise ValueError("state.json: ожидался объект")
                    new = parse_nicks(raw.get("allowed"))
                    raw["allowed"] = new
                    self.state = raw
                    self.state.setdefault("allowed", new)
                    if not isinstance(self.state.get("muted"), dict):
                        self.state["muted"] = {}
                    self.save_state()
                    self._write_allowed_file()
                    self.log("Список разрешённых обновлён из state.json")
                self._m_allowed = _mtime(self._allowed_path)
            except Exception as e:
                # файл правят прямо сейчас/ошибка в JSON — оставляем прежний список, повторим позже
                self._m_allowed, self._m_state = ma, ms
                self.log(f"Не удалось прочитать список разрешённых: {e}")

    def set_allowed(self, nicks):
        with self._sync_lock:
            self.sync_allowed()
            self.state["allowed"] = list(nicks)
            self.save_state()
            self._write_allowed_file()

    # ---- кому TTS запрещён: data/blocked_users.txt (насовсем) и муты в state.json (на время) ----
    def _write_blocked_file(self):
        head = ("# Кому НЕЛЬЗЯ озвучивать — ни через !!!, ни за баллы (VIP и модерам тоже; владельцу — можно всегда)\n"
                "# Ники через пробел, запятую или с новой строки. '#' — комментарий.\n"
                "# Файл можно править пока бот запущен — изменения подхватятся сами.\n")
        self._blocked_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._blocked_path.with_suffix(".tmp")
        tmp.write_text(head + "\n".join(self.blocked) + "\n", encoding="utf-8")
        tmp.replace(self._blocked_path)
        self._m_blocked = _mtime(self._blocked_path)

    def sync_blocked(self):
        with self._sync_lock:
            m = _mtime(self._blocked_path)
            if m == self._m_blocked:
                return
            try:
                self.blocked = parse_nicks(self._blocked_path.read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                self.log(f"Не удалось прочитать {BLOCKED_FILE}: {e}")
            self._m_blocked = m

    def set_blocked(self, nicks):
        with self._sync_lock:
            self.blocked = [n for n in nicks if n != self.chan]
            self._write_blocked_file()

    def mute_left(self, login):
        """Сколько секунд ещё длится мут (0 — не в муте). Истёкший мут убирается."""
        until = self.state["muted"].get(login)
        if until is None:
            return 0
        try:
            left = float(until) - time.time()
        except (TypeError, ValueError):
            left = 0
        if left <= 0:
            with self._sync_lock:
                self.state["muted"].pop(login, None)
                self.save_state()
            return 0
        return left

    def denied(self, login, is_b):
        if is_b:
            return False
        self.sync_blocked()
        return login in self.blocked or self.mute_left(login) > 0

    def cmd_mute(self, sub, args):
        """!tts mute <ник> [минуты] / !tts unmute <ник> — модеры, главный модер, владелец."""
        nicks = parse_nicks(args[:1])
        if not nicks:
            return f"Формат: !tts mute <ник> [минуты, по умолчанию {MUTE_DEFAULT_MIN}] / !tts unmute <ник>"
        nick = nicks[0]
        self.sync_allowed()
        if sub == "unmute":
            with self._sync_lock:
                had = self.state["muted"].pop(nick, None) is not None
                self.save_state()
            return f"{nick} снова может использовать TTS" if had else f"{nick} и так не в муте"
        if nick == self.chan:
            return "Владельца канала замутить нельзя"
        mins = MUTE_DEFAULT_MIN
        if len(args) > 1:
            m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:м|мин|m|min)?", args[1].lower())
            if not m or float(m.group(1).replace(",", ".")) <= 0:
                return "Минуты — числом: !tts mute <ник> 15"
            mins = min(float(m.group(1).replace(",", ".")), MUTE_MAX_MIN)
        with self._sync_lock:
            self.state["muted"][nick] = time.time() + mins * 60
            self.save_state()
        self.drop_ids(list(self.recent_ids.pop(nick, [])))   # уже стоящее в очереди — не договариваем
        return f"{nick} не может использовать TTS {mins:g} мин"

    # ---- управление подключением ----
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.running():
            return
        if not self.token or not self.chan:
            raise BotError("Заполни токен и канал на вкладке «Настройки»")
        if self.cfg.get("tera_preload", True) and self.voices.tera_defs():
            d = next(iter(self.voices.tera_defs().values()))
            self.tera.preload(d.get("model", "TeraTTS/glados2-g2p-vits"))
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()

    def _thread_main(self):
        loop = self.loop
        asyncio.set_event_loop(loop)
        self.task = loop.create_task(self._irc_run())
        try:
            loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.status = "error"
            self.log(f"Сбой: {e}")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            if self.status != "error":
                self.status = "stopped"

    def stop(self):
        loop, task, th = self.loop, self.task, self.thread
        if loop and task and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)
        if th and th.is_alive():
            th.join(3)
        self.status = "stopped" if self.status != "error" else self.status
        self.log("Остановлено")

    # ---- Twitch API ----
    def _http(self, method, url, headers, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")

    def _validate(self, token):
        try:
            return self._http("GET", "https://id.twitch.tv/oauth2/validate", {"Authorization": "OAuth " + token})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TokenRejected("Twitch отклонил токен (401): он просрочен или неверный. "
                                    "Нажми «Войти через Twitch» на вкладке «Настройки» — токен получится заново.")
            raise BotError(f"Ошибка проверки токена: HTTP {e.code}")
        except Exception as e:
            raise BotError(f"Нет связи с Twitch: {e}")

    def check_token(self, token=None):
        """Блокирующая проверка токена (для кнопки в окне). Возвращает текст отчёта."""
        info = self._validate(extract_token(token) if token else self.token)
        scopes = set(info.get("scopes", []))
        missing = [s for s in ("chat:read", "chat:edit") if s not in scopes]
        txt = f"Токен рабочий. Аккаунт: {info['login']}."
        if missing:
            txt += f" Не хватает прав: {', '.join(missing)}."
        if "channel:manage:redemptions" not in scopes:
            txt += " Нет channel:manage:redemptions — награду и цену бот менять не сможет."
        return txt

    def try_refresh(self):
        """Обновляет токен через refresh-токен (если его выдал мастер входа). True — получилось.
        Обновляем тем же способом, каким входили: напрямую у Twitch или через twitchtokengenerator."""
        rt = (self.cfg.get("refresh_token") or "").strip()
        if not rt:
            return False
        try:
            if self.cfg.get("auth_method") == "twitch":
                new = twitch_auth.refresh_direct(rt)
            else:
                new = twitch_auth.refresh(rt)
        except twitch_auth.AuthError as e:
            self.log(f"Автообновление токена не удалось: {e}")
            return False
        self.cfg["oauth_token"] = new["token"]
        if new["refresh"]:
            self.cfg["refresh_token"] = new["refresh"]
        self.client_id = ""
        save_cfg(self.cfg)
        self.log("Токен Twitch обновлён автоматически")
        return True

    async def auth(self):
        try:
            info = await asyncio.to_thread(self._validate, self.token)
        except TokenRejected:
            if not await asyncio.to_thread(self.try_refresh):
                raise
            info = await asyncio.to_thread(self._validate, self.token)
        self.nick, self.client_id, self.user_id = info["login"], info["client_id"], info["user_id"]
        scopes = set(info.get("scopes", []))
        self.can_manage = self.nick == self.chan and "channel:manage:redemptions" in scopes
        self.log(f"Аккаунт: {self.nick}; управление наградой: {'да' if self.can_manage else 'нет'}")

    async def ensure_auth(self):
        if not self.client_id:
            await self.auth()

    async def helix(self, method, path, params=None, body=None):
        url = "https://api.twitch.tv/helix/" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in (1, 2):
            headers = {"Authorization": "Bearer " + self.token, "Client-Id": self.client_id,
                       "Content-Type": "application/json"}
            try:
                return await asyncio.to_thread(self._http, method, url, headers, body)
            except urllib.error.HTTPError as e:   # токен просрочился за время стрима — обновляем и повторяем
                if e.code != 401 or attempt == 2 or not await asyncio.to_thread(self.try_refresh):
                    raise
                await self.auth()

    # ---- IRC ----
    def send(self, text):
        if self.writer:
            text = text.replace("\r", " ").replace("\n", " ")[:450]
            self.writer.write(f"PRIVMSG #{self.chan} :{text}\r\n".encode())

    async def _irc_run(self):
        self.status = "connecting"
        try:
            await self.ensure_auth()
        except BotError as e:
            self.status = "error"
            self.log(str(e))
            return
        delay = 1
        first = True
        try:
            while True:
                try:
                    if not first:   # токен живёт несколько часов: перед переподключением проверяем/обновляем
                        self.client_id = ""
                        try:
                            await self.ensure_auth()
                        except TokenRejected:
                            raise                         # токен мёртв и не обновился — нужен вход заново
                        except BotError as e:
                            raise ConnectionError(str(e))  # нет сети — это просто обрыв, пробуем дальше
                    first = False
                    await self._session()
                    delay = 1
                except BotError as e:
                    self.status = "error"
                    self.log(str(e))
                    return
                except (OSError, ConnectionError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
                    self.log(f"Обрыв: {e}; переподключение через {delay}с")
                self.status = "connecting"
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
        finally:
            if self.writer:
                try:
                    self.writer.close()
                except Exception:
                    pass
                self.writer = None

    async def _session(self):
        reader, writer = await asyncio.open_connection("irc.chat.twitch.tv", 6697,
                                                       ssl=ssl.create_default_context())
        self.writer = writer
        writer.write(f"PASS oauth:{self.token}\r\nNICK {self.nick}\r\n".encode())
        writer.write(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
        writer.write(f"JOIN #{self.chan}\r\n".encode())
        await writer.drain()
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=420)
            if not raw:
                raise ConnectionError("соединение закрыто")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("PING"):
                writer.write(("PONG" + line[4:] + "\r\n").encode())
                await writer.drain()
                continue
            tags, prefix, cmd, rest = parse_irc(line)
            if cmd == "001":
                self.status = "connected"
                self.log(f"Подключён к #{self.chan}")
            elif cmd == "PRIVMSG":
                _, _, text = rest.partition(" :")
                await self.on_privmsg(tags, prefix.split("!")[0].lower(), text)
            elif cmd in ("CLEARMSG", "CLEARCHAT"):
                self.on_clear(cmd, tags, rest)
            elif cmd == "RECONNECT":
                return
            elif cmd == "NOTICE" and "authentication failed" in rest.lower():
                if await asyncio.to_thread(self.try_refresh):
                    raise ConnectionError("токен обновлён — переподключаюсь")
                raise BotError("Twitch отклонил токен при входе в чат. Получи новый.")
            await writer.drain()

    # ---- логика чата ----
    def drop_ids(self, ids):
        """Сообщения удалены модером: не озвучивать из очереди, а то, что звучит сейчас, — оборвать."""
        ids = [i for i in ids if i]
        if len(self.dropped) > 500:
            self.dropped.clear()
        self.dropped.update(ids)
        if self.player.current_id and self.player.current_id in ids:
            self.player.skip.set()

    def on_clear(self, cmd, tags, rest):
        if cmd == "CLEARMSG":
            self.drop_ids([tags.get("target-msg-id")])
            return
        _, _, target = rest.partition(" :")
        if target.strip():  # бан или таймаут зрителя — убираем все его сообщения
            self.drop_ids(list(self.recent_ids.pop(target.strip().lower(), [])))
        else:               # модер очистил весь чат
            self.player.clear()
            self.player.skip.set()

    async def on_privmsg(self, tags, login, text):
        if text.startswith("\x01ACTION "):
            text = text[8:].rstrip("\x01")
        text = strip_emotes(text, tags.get("emotes", "")).strip()
        if not text:
            return
        badges = tags.get("badges", "")
        is_b = "broadcaster/" in badges
        is_mod = is_b or tags.get("mod") == "1" or "moderator/" in badges   # «moderator/» ловит и lead_moderator/
        is_vip = "vip/" in badges
        first = text.lower().split(" ", 1)[0]

        rid = tags.get("custom-reward-id")
        if rid and rid == self.state.get("reward_id"):
            if self.denied(login, is_b):   # баллы уже списаны — вернуть можно только вручную на Twitch
                self.send(f"@{login}, тебе TTS сейчас недоступен")
                return
            self.speak_reward(login, tags, text)  # за баллы — всегда озвучка, команды внутри не съедают баллы
            return

        if first == "!skip":
            if is_mod:
                self.player.skip.set()
            return

        if first == "!tts":
            args = text.split()[1:]
            if args and args[0].lower() in ("mute", "unmute"):
                if is_mod:
                    self.send(self.cmd_mute(args[0].lower(), args[1:]))
                return
            self.cmd_voice(login, text[4:].strip())
            return

        if text.startswith("!!!"):
            body = text[3:].strip()
            parts = body.split()
            if not parts:
                return
            if parts[0].lower() == "tts" and len(parts) > 1 and parts[1].lower() in ADMIN_SUBS:
                if is_mod:
                    self.send(await self.admin(parts[1:], is_b))
                return
            self.sync_allowed()
            if self.denied(login, is_b):
                return
            if is_mod or is_vip or login in self.state["allowed"]:
                self.speak(login, tags, body, cooldown=not is_mod)
            return

        if rid and not self.state.get("reward_id"):
            self.log(f"Награда с id {rid} (привяжи: !!!tts reward id {rid})")

    def speak_reward(self, login, tags, text):
        """Текст награды: «!!!текст» -> «текст»; «!tts голос» — смена голоса; «!tts голос текст» — смена и озвучка."""
        if text.startswith("!!!"):
            text = text[3:].strip()
        if text.lower().split(" ", 1)[0] == "!tts":
            rest = text[4:].strip()
            name, _, said = rest.partition(" ")
            if self.voices.exists(name):
                self.cmd_voice(login, name)
                text = said.strip()
            else:
                text = rest
            if not rest:
                self.cmd_voice(login, "")
        if text:
            self.speak(login, tags, text, cooldown=False)

    def pick_voice(self, login):
        v = (self.user_voices.get(login) or self.cfg.get("default_voice") or "").lower()
        if self.voices.exists(v):
            return v
        names = self.voices.names()
        return names[0] if names else None

    def speak(self, login, tags, text, cooldown):
        if not self.enabled:
            return
        text = clean(text, int(self.cfg.get("max_chars", 200)))
        if not text or self.bl.hit(text):
            return
        text = self.replace(text)
        if not text:
            return
        now = time.time()
        if cooldown and now - self.last_use.get(login, 0) < float(self.cfg.get("user_cooldown_sec", 5)):
            return
        win = float(self.cfg.get("dup_window_sec", 30) or 0)
        if cooldown and win > 0:   # модеров и баллы не трогаем (cooldown=False)
            key = " ".join(re.findall(r"\w+", text.lower()))
            if key and now - self.recent_texts.get(key, 0) < win:
                return
            if len(self.recent_texts) > 300:
                self.recent_texts = {k: t for k, t in self.recent_texts.items() if now - t < win}
            self.recent_texts[key] = now
        voice = self.pick_voice(login)
        if not voice:
            self.log("Нет ни одного голоса — вкладка «Голоса» → «Скачать голоса…»")
            return
        if self.player.q.qsize() >= int(self.cfg.get("max_queue", 15)):
            return
        self.last_use[login] = now
        name = tags.get("display-name") or login
        if self.cfg.get("say_name") and not self.bl.hit(name):  # ник из чёрного списка не читаем
            text = f"{name} говорит: {text}"
        if tags.get("id"):
            self.recent_ids.setdefault(login, deque(maxlen=20)).append(tags["id"])
        self.player.q.put((voice, text, tags.get("id")))

    def replace(self, text):
        if not self.cfg.get("replace_on", True):
            return text
        try:
            return self.repl.apply(text, bool(self.cfg.get("replace_strip_emoji", True)))
        except Exception as e:  # словарь не должен ломать озвучку
            self.log(f"Словарь замен: ошибка ({type(e).__name__}: {e}) — читаю как есть")
            return text

    def cmd_voice(self, login, arg):
        names = self.voices.names()
        if not arg:
            line = "Голоса: " + ", ".join(names) + ". Выбрать: !tts <имя>"
            while line:
                cut = line[:420]
                if len(line) > 420 and ", " in cut:
                    cut = cut[:cut.rfind(", ") + 1]
                self.send(cut)
                line = line[len(cut):].strip()
            return
        name = arg.lower()
        if self.voices.exists(name):
            self.user_voices[login] = name
            save_json(DATA / "user_voices.json", self.user_voices)
            self.send(f"@{login}, голос: {name}")
        else:
            self.send(f"@{login}, нет такого голоса. Список: !tts")

    def test_say(self, text, voice=None):
        voice = (voice or self.cfg.get("default_voice") or "").lower()
        if not self.voices.exists(voice):
            names = self.voices.names()
            if not names:
                raise ValueError("Нет ни одного голоса")
            voice = names[0]
        self.player.q.put((voice, self.replace(clean(text, 300)) or "Проверка звука", None))

    # ---- админ-команды (чат и панель) ----
    async def admin(self, parts, is_b):
        sub = parts[0].lower()
        arg = parts[1].lstrip("@").lower() if len(parts) > 1 else ""
        self.sync_allowed()
        allowed = self.state["allowed"]
        try:
            if sub == "add" and arg:
                nicks = parse_nicks(parts[1:])
                new = [n for n in nicks if n not in allowed]
                if new:
                    self.set_allowed(allowed + new)
                if len(nicks) == 1:
                    return f"{nicks[0]} теперь может использовать TTS через !!!"
                return f"Добавлено: {len(new)} из {len(nicks)}"
            if sub in ("del", "remove") and arg:
                nicks = parse_nicks(parts[1:])
                if any(n in allowed for n in nicks):
                    self.set_allowed([n for n in allowed if n not in nicks])
                return (f"{nicks[0]} больше не может использовать TTS" if len(nicks) == 1
                        else f"Удалено: {len(nicks)}")
            if sub == "set":
                nicks = parse_nicks(parts[1:])
                self.set_allowed(nicks)
                return f"Список заменён: {len(nicks)} ников"
            if sub == "list":
                return "Разрешены: " + (", ".join(allowed) or "никто (кроме модеров и VIP)")
            if sub == "block" and arg:
                nicks = parse_nicks(parts[1:])
                if self.chan in nicks:
                    return "Владельца канала заблокировать нельзя"
                self.sync_blocked()
                self.set_blocked(self.blocked + [n for n in nicks if n not in self.blocked])
                for n in nicks:
                    self.drop_ids(list(self.recent_ids.pop(n, [])))
                return (f"{nicks[0]} больше не может использовать TTS (!!! и баллы)" if len(nicks) == 1
                        else f"Заблокировано: {len(nicks)}")
            if sub == "unblock" and arg:
                nicks = parse_nicks(parts[1:])
                self.sync_blocked()
                self.set_blocked([n for n in self.blocked if n not in nicks])
                return f"{nicks[0]} снова может использовать TTS" if len(nicks) == 1 else f"Разблокировано: {len(nicks)}"
            if sub == "ban" and len(parts) > 1:
                self.bl.add(" ".join(parts[1:]))
                return "Добавлено в чёрный список"
            if sub == "unban" and len(parts) > 1:
                self.bl.remove(" ".join(parts[1:]))
                return "Убрано из чёрного списка"
            if sub == "reload":
                self.voices.scan()
                self.bl.load()
                self.repl.load()
                return "Голоса: " + ", ".join(self.voices.names())
            if sub in ("price", "reward") and not is_b:
                return "Это может только владелец канала"
            if sub == "price" and arg.isdigit():
                await self.ensure_auth()
                if not (self.can_manage and self.state.get("reward_id")):
                    return "Нужна награда, созданная ботом: «Создать награду» / !!!tts reward create <цена>"
                await self.helix("PATCH", "channel_points/custom_rewards",
                                 {"broadcaster_id": self.user_id, "id": self.state["reward_id"]},
                                 {"cost": int(arg)})
                self.state["price"] = int(arg)
                self.save_state()
                return f"Цена награды TTS: {arg}"
            if sub == "reward" and arg == "create":
                await self.ensure_auth()
                if not self.can_manage:
                    return "Токену нужен scope channel:manage:redemptions и аккаунт владельца канала"
                cost = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 500
                res = await self.helix("POST", "channel_points/custom_rewards",
                                       {"broadcaster_id": self.user_id},
                                       {"title": "TTS — озвучка сообщения", "cost": cost,
                                        "prompt": "Введи текст, который озвучит бот",
                                        "is_user_input_required": True,
                                        "is_global_cooldown_enabled": True, "global_cooldown_seconds": 10})
                self.state["reward_id"] = res["data"][0]["id"]
                self.state["price"] = cost
                self.save_state()
                return f"Награда создана, цена {cost}"
            if sub == "reward" and arg == "id" and len(parts) > 2:
                self.state["reward_id"] = parts[2]
                self.save_state()
                return "Награда привязана"
        except urllib.error.HTTPError as e:
            return f"Ошибка Twitch API {e.code}" + (" (награда с таким названием уже есть?)" if e.code == 400 else "")
        except Exception as e:
            return f"Ошибка: {e}"
        return ("Команды: add|del <ник>, list, block|unblock <ник>, ban|unban <слово>, price <N>, "
                "reward create [цена]|id <id>, reload. Мут: !tts mute <ник> [мин], !tts unmute <ник>")

    # ---- панель OBS ----
    def snapshot(self):
        self.sync_allowed()
        self.sync_blocked()
        muted = []
        for n in sorted(self.state["muted"]):
            left = self.mute_left(n)
            if left > 0:
                muted.append({"v": n, "t": f"{n} · {-int(-left // 60)} мин"})
        return {
            "status": self.status,
            "channel": self.chan,
            "enabled": self.enabled,
            "volume": int(round(self.player.volume * 100)),
            "queue": self.player.q.qsize(),
            "speaking": self.player.current,
            "voices": self.voices.names(),
            "default_voice": self.cfg.get("default_voice", ""),
            "allowed": list(self.state["allowed"]),
            "blacklist": list(self.bl.raw),
            "blocked": list(self.blocked),
            "muted": muted,
            "price": self.state.get("price", 0),
            "has_reward": bool(self.state.get("reward_id")),
            "sounds": self.sounds.names(),
            "snd": {k: self.cfg.get(k, DEFAULT_CFG[k]) for k in
                    ("sounds_on", "sound_max_per_msg", "sound_max_sec", "sound_volume")},
            "log": list(self.logs)[-25:],
        }

    def do_action(self, a):
        act = a.get("action")
        val = str(a.get("value", "")).strip()
        if act == "github":
            webbrowser.open(GITHUB)
            return "Открываю GitHub в браузере"
        elif act == "skip":
            self.player.skip.set()
        elif act == "clear":
            self.player.clear()
            self.player.skip.set()
            return "Очередь очищена"
        elif act == "toggle":
            self.enabled = not self.enabled
            if not self.enabled:
                self.player.clear()
                self.player.skip.set()
            return "TTS включён" if self.enabled else "TTS выключен"
        elif act == "volume":
            self.cfg["volume"] = max(0, min(200, int(val)))
            self.player.volume = self.cfg["volume"] / 100
            save_cfg(self.cfg)
        elif act == "default_voice":
            if not self.voices.exists(val):
                raise ValueError("Нет такого голоса")
            self.cfg["default_voice"] = val.lower()
            save_cfg(self.cfg)
            return f"Голос по умолчанию: {val}"
        elif act == "allow_add":
            return asyncio.run(self.admin(["add", val], True))
        elif act == "allow_set":
            return asyncio.run(self.admin(["set"] + val.split(), True))
        elif act == "allow_del":
            return asyncio.run(self.admin(["del", val], True))
        elif act == "block_add":
            return asyncio.run(self.admin(["block"] + val.split(), True))
        elif act == "block_del":
            return asyncio.run(self.admin(["unblock", val], True))
        elif act == "mute_add":
            return self.cmd_mute("mute", val.split())
        elif act == "mute_del":
            return self.cmd_mute("unmute", [val])
        elif act == "ban_add":
            return asyncio.run(self.admin(["ban", val], True))
        elif act == "ban_del":
            return asyncio.run(self.admin(["unban", val], True))
        elif act == "price":
            return asyncio.run(self.admin(["price", val], True))
        elif act == "reward_create":
            return asyncio.run(self.admin(["reward", "create", val or "500"], True))
        elif act == "repl_get":
            return self.repl.get_text()
        elif act == "repl_set":
            n = self.repl.set_text(a.get("value", ""))
            return f"Словарь сохранён: {n} замен всего (вместе с готовым)"
        elif act == "repl_try":
            return "Прочитаю так: " + (sounds.to_text(self.replace(clean(val, 300))) or "(пусто)")
        elif act == "snd_add":
            import base64
            name = self.sounds.add(a.get("name", ""), base64.b64decode(str(a.get("data", ""))))
            return f"Звук [{name}] добавлен. В словаре: слово = [{name}]"
        elif act == "snd_del":
            return f"Звук [{self.sounds.remove(val)}] удалён"
        elif act == "snd_play":
            if not self.cfg.get("sounds_on", True):
                return "Звуки выключены — включи галочку «Звуки вместо слов»"
            self.player.q.put((None, sounds.SND + val.lower() + sounds.SND, None))
        elif act == "snd_cfg":
            lim = {"sound_max_per_msg": (0, 20), "sound_max_sec": (0.5, 30), "sound_volume": (0, 200)}
            for k, (lo, hi) in lim.items():
                if k in a:
                    v = max(lo, min(hi, float(a[k])))
                    self.cfg[k] = int(v) if k != "sound_max_sec" else round(v, 1)
            if "sounds_on" in a:
                self.cfg["sounds_on"] = bool(a["sounds_on"])
            save_cfg(self.cfg)
            return "Настройки звуков сохранены"
        elif act == "test":
            self.test_say(val or "Проверка звука", a.get("voice") or None)
        else:
            raise ValueError("Неизвестное действие")
        return ""
