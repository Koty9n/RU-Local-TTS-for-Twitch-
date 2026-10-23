"""Пути с русскими буквами («C:\\Users\\Вова\\…», «Новая папка») ломают две библиотеки на C:
  • pycrfsuite (часть ruaccent, части речи) — без неё ударения отключаются целиком;
  • espeak-ng у Piper — без него голоса Piper не говорят вовсе.

Путь делается латинским: короткое имя Windows (8.3), а если его нет — копия в C:\\ProgramData\\TwitchTTS.
patch_pycrfsuite() — до загрузки RUAccent (accent.py, tera_worker.py); ascii_dir(...) — для espeak_data_dir Piper.
"""
import os
import shutil


def _is_ascii(p):
    try:
        str(p).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _short_path(p):
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, len(buf))
        return buf.value if 0 < n < len(buf) else None
    except Exception:
        return None


def _program_data():
    base = os.environ.get("ProgramData") or "C:\\ProgramData"
    return os.path.join(base if _is_ascii(base) else "C:\\ProgramData", "TwitchTTS")


def _ascii_copy(p):
    dst_dir = os.path.join(_program_data(), "models")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(p) if _is_ascii(os.path.basename(p)) else "model.bin")
    if not (os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(p)):
        shutil.copyfile(p, dst)
    return dst


def ascii_path(p):
    """Путь к тому же файлу, но латиницей. Если ничего не вышло — исходный путь."""
    p = str(p)
    if _is_ascii(p):
        return p
    s = _short_path(p)
    if s and _is_ascii(s):
        return s
    try:
        return _ascii_copy(p)
    except Exception:
        return p


def ascii_dir(p):
    """То же для папки (данные espeak-ng у Piper): короткое имя или копия папки в C:\\ProgramData\\TwitchTTS."""
    p = str(p)
    if _is_ascii(p):
        return p
    s = _short_path(p)
    if s and _is_ascii(s):
        return s
    try:
        dst = os.path.join(_program_data(), os.path.basename(p) if _is_ascii(os.path.basename(p)) else "data")
        stamp = os.path.join(dst, ".tts_copied")
        if not os.path.exists(stamp):
            shutil.copytree(p, dst, dirs_exist_ok=True)
            open(stamp, "w").close()
        return dst
    except Exception:
        return p


def patch_pycrfsuite():
    try:
        import pycrfsuite
    except ImportError:
        return
    if getattr(pycrfsuite, "_tts_ascii_patch", False):
        return
    base = pycrfsuite.Tagger

    class Tagger(base):
        def open(self, name, *args, **kwargs):
            return super().open(ascii_path(name), *args, **kwargs)

    pycrfsuite.Tagger = Tagger
    pycrfsuite._tts_ascii_patch = True
