"""Звуки вместо слов: в словаре замен «kekw = [смех]» -> вместо слова играет data/sounds/смех.wav.

Словарь ставит на место звука метку SND+имя+SND (зритель её напечатать не может — replacements вырезает SND
из входящего текста), плеер режет текст по меткам на куски «текст / звук / текст».
Ограничители (config.json, правятся в панели): sounds_on, sound_max_per_msg, sound_max_sec, sound_volume.
Файлы — только WAV (из панели любой mp3/ogg/wav перегоняется в WAV браузером). Читаются один раз и держатся
в памяти уже выровненными по громкости; перечитываются, только когда поменялась дата файла.
"""
import re
import time
import wave
from pathlib import Path

SND = "\x01"
MARK_RE = re.compile(SND + "([^" + SND + "]*)" + SND)
NAME_RE = re.compile(r"[^\w\- ]+")
TARGET_RMS = 0.12   # примерно громкость голосов Piper/GLaDOS
PEAK = 0.9
FADE_SEC = 0.05     # затухание в конце обрезанного звука, чтобы не щёлкало


def safe_name(name):
    """Имя звука = имя файла: буквы, цифры, пробел, «-», «_»; до 40 знаков."""
    return re.sub(r"\s+", " ", NAME_RE.sub("", str(name or ""))).strip()[:40]


def to_marks(value):
    """Правая часть строки словаря: «ля [барабан]» -> «ля \x01барабан\x01»."""
    return re.sub(r"\[([^\[\]]{1,40})\]", lambda m: f" {SND}{safe_name(m.group(1)).lower()}{SND} ", value)


def to_text(text):
    """Для показа (панель, «сейчас звучит»): метки обратно в [имя]."""
    return MARK_RE.sub(lambda m: f"[{m.group(1)}]", text)


def read_wav(path):
    """WAV (8/16/24/32 бит PCM, моно или стерео) -> (частота, моно float32 от -1 до 1)."""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        a = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
             << 8 >> 8).astype(np.float32) / 8388608
    else:
        a = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648
    if ch > 1:
        a = a[: len(a) // ch * ch].reshape(-1, ch).mean(axis=1)
    return rate, a


def level(a):
    """Выровнять громкость: средняя — как у голоса, пики не выше PEAK."""
    import numpy as np
    if not len(a):
        return a
    peak = float(np.abs(a).max())
    rms = float(np.sqrt(np.mean(a * a)))
    if peak < 1e-4:
        return a
    return a * min(PEAK / peak, TARGET_RMS / max(rms, 1e-6))


class Sounds:
    def __init__(self, folder, cfg, log=print):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cfg, self.log = cfg, log
        self.cache = {}            # имя -> (mtime, частота, float32)
        self._names, self._seen = {}, None
        self._checked = 0.0
        self._warned = set()

    # ---- список файлов (папку смотрим не чаще раза в 2 с)
    def _scan(self):
        now = time.monotonic()
        if self._seen is not None and now - self._checked < 2:
            return
        self._checked = now
        try:
            stamp = self.dir.stat().st_mtime_ns
        except OSError:
            stamp = None
        if stamp == self._seen:
            return
        self._seen = stamp
        self._names = {p.stem.lower(): p for p in sorted(self.dir.glob("*.wav"))}

    def names(self):
        self._scan()
        return [p.stem for p in self._names.values()]

    def get(self, name):
        """(частота, моно int16 bytes) уже с громкостью/обрезкой из настроек, или None."""
        import numpy as np
        self._scan()
        p = self._names.get(name.lower())
        if p is None:
            if name not in self._warned:
                self._warned.add(name)
                self.log(f"Звук [{name}] не найден — добавь его в панели OBS («Словарь» → «Звуки»)")
            return None
        try:
            mt = p.stat().st_mtime_ns
            hit = self.cache.get(name.lower())
            if not hit or hit[0] != mt:
                rate, a = read_wav(p)
                hit = self.cache[name.lower()] = (mt, rate, level(a))
        except Exception as e:
            if name not in self._warned:
                self._warned.add(name)
                self.log(f"Звук [{name}] не читается ({e}). Нужен WAV — проще всего загрузить его через панель OBS")
            return None
        _, rate, a = hit
        max_n = int(float(self.cfg.get("sound_max_sec", 3)) * rate)
        if max_n > 0 and len(a) > max_n:
            a = a[:max_n].copy()
            fade = min(len(a), int(FADE_SEC * rate))
            a[len(a) - fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        a = a * (float(self.cfg.get("sound_volume", 80)) / 100)
        return rate, (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()

    def split(self, text):
        """Текст с метками -> [("text", "...") | ("sound", имя)]. Лишние звуки (сверх лимита) выкидываются."""
        on = bool(self.cfg.get("sounds_on", True))
        left = int(self.cfg.get("sound_max_per_msg", 3)) if on else 0
        out, pos = [], 0
        for m in MARK_RE.finditer(text):
            out.append(("text", text[pos:m.start()]))
            if left > 0 and m.group(1):
                out.append(("sound", m.group(1)))
                left -= 1
            pos = m.end()
        out.append(("text", text[pos:]))
        return [(k, v.strip() if k == "text" else v) for k, v in out if k == "sound" or re.search(r"\w", v)]

    # ---- для панели
    def add(self, name, wav_bytes):
        name = safe_name(name)
        if not name:
            raise ValueError("Пустое имя звука")
        if not wav_bytes.startswith(b"RIFF"):
            raise ValueError("Это не WAV")
        tmp = self.dir / (name + ".tmp")
        tmp.write_bytes(wav_bytes)
        try:
            read_wav(tmp)   # проверка, что читается
        except Exception as e:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"Файл не читается: {e}")
        for old in self.dir.glob("*.wav"):   # то же имя другим регистром — заменяем
            if old.stem.lower() == name.lower():
                old.unlink()
        tmp.replace(self.dir / (name + ".wav"))
        self._seen = None
        self._warned.discard(name.lower())
        return name

    def remove(self, name):
        self._scan()
        p = self._names.get(str(name).lower())
        if p is None:
            raise ValueError("Нет такого звука")
        p.unlink()
        self.cache.pop(p.stem.lower(), None)
        self._seen = None
        return p.stem
