"""Ударения для русского текста: RUAccent (модель tiny2) -> текст, понятный Piper.

RUAccent ставит «+» перед ударной гласной: «зам+ок». Но Piper (через espeak-ng) знак «+» может не понять,
поэтому приложение само проверяет, какой формат пометки понимает ИМЕННО ваш Piper (detect_mark_mode):
  combining — гласная + U+0301 («замо́к»),  upper — ударная гласная заглавной («замОк»),  plus — «зам+ок».
Если ни один формат не понят, включается запасной режим «phoneme»: ударение переставляется в фонемах (retarget_stress).

Свои ударения можно ставить вручную: если в тексте уже есть «+», RUAccent не вызывается, текст берётся как есть.
"""
import inspect
import re
import threading
from collections import OrderedDict
from pathlib import Path

MODEL = "tiny2"
# если выбранная модель не подошла к установленной версии ruaccent (бывает «Required inputs ['token_type_ids'] are missing»),
# перебираем запасные — тот же порядок, что в tera_worker.py
FALLBACK = ["tiny2", "tiny", "turbo3.1", "turbo3"]
TEST_PHRASE = "Привет, замок на двери."
UNKNOWN_PROBE = "имба"    # слова нет в словаре RUAccent — проверяет нейросеть ударений для незнакомых слов
RU_VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
MARKS = ("combining", "upper", "plus")          # порядок проверки при автоопределении
_STRESS_RE = re.compile(r"\+([" + RU_VOWELS + r"])")
_WORD_RE = re.compile(r"[А-Яа-яЁё+]+(?:-[А-Яа-яЁё+]+)*")
_SENT_SPLIT = re.compile(r"((?<=[.!?…])\s+|\n+)")

# гласные в IPA, которые выдаёт espeak для русского (проверка по первому символу фонемы)
IPA_VOWELS = set("aɐəɪɨɛɵʉɔɑæɜʊʌeiouyɤɯœøɶɘɚᵻ")


# ------------------------------------------------------------ форматы пометок
def has_manual_stress(text):
    return "+" in text


def to_marks(text, mode):
    """Текст с «+» (формат RUAccent) -> текст с пометками нужного формата."""
    if mode == "plus":
        return text
    if mode == "combining":
        text = _STRESS_RE.sub(lambda m: m.group(1) + "\u0301", text)
    elif mode == "upper":
        text = _STRESS_RE.sub(lambda m: m.group(1).upper(), text)
    return text.replace("+", "")        # «none» и хвосты: одиночные «+» не должны попасть в озвучку


def strip_marks(text):
    return to_marks(text, "none").replace("\u0301", "")


def russian_words(text):
    """Русские слова текста (вместе с «+» внутри) — в том порядке, в каком их читает синтезатор."""
    return _WORD_RE.findall(text)


# ------------------------------------------------------------ RUAccent
class Accentizer:
    """Ленивая обёртка над RUAccent: грузится при первом использовании, при любой беде молча отключается."""

    def __init__(self, workdir, log=print, model=MODEL, use_dictionary=True, tiny_mode=False):
        self.workdir = Path(workdir)
        self.log = log
        self.model_name = model
        self.use_dictionary = use_dictionary
        self.tiny_mode = tiny_mode
        self.model = None
        self.model_used = None
        self.state = "new"          # new | ready | off
        self.loading = False
        self.lock = threading.Lock()
        self.cache = OrderedDict()

    def _load(self):
        try:   # путь с русскими буквами ломает часть ruaccent (pycrfsuite) — подменяем путь на латинский
            import ascii_paths
            ascii_paths.patch_pycrfsuite()
        except Exception:
            pass
        try:
            from ruaccent import RUAccent
        except Exception:
            self.log("Ударения выключены: не установлен пакет ruaccent (pip install ruaccent).")
            self.state = "off"
            return
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.log(f"Загружаю RUAccent ({self.model_name}); при первом запуске скачиваются модель и словарь…")
        sizes = [self.model_name] + [m for m in FALLBACK if m != self.model_name]
        for size in sizes:
            try:
                ctor = inspect.signature(RUAccent.__init__).parameters
                acc = RUAccent(workdir=str(self.workdir)) if "workdir" in ctor else RUAccent()
                sig = inspect.signature(acc.load).parameters
                kw = {"omograph_model_size": size, "use_dictionary": self.use_dictionary}
                if "workdir" in sig:
                    kw["workdir"] = str(self.workdir)
                if "tiny_mode" in sig:
                    kw["tiny_mode"] = bool(self.tiny_mode)
                acc.load(**kw)
                acc.process_all(TEST_PHRASE)        # настоящая проверка: ловит несовпадение версий пакета и модели
                self.model, self.state, self.model_used = acc, "ready", size
                self.log(f"RUAccent готов (модель {size})" + ("" if size == self.model_name else f" — выбранная «{self.model_name}» не подошла"))
                try:
                    acc.process_all(UNKNOWN_PROBE)  # слова не из словаря идут через отдельную нейросеть
                except Exception as e:
                    self.log(f"ВНИМАНИЕ: ударения не работают для слов не из словаря ({type(e).__name__}) — "
                             "фразы со сленгом прочитаются без ударений. Обычно лечится: pip install \"transformers<5\"")
                return
            except Exception as e:
                self.log(f"Ударения: модель «{size}» не подошла: {type(e).__name__}: {e}")
        self.log("Ударения выключены: ни одна модель RUAccent не заработала. Попробуй: pip install -U ruaccent")
        self.state = "off"

    def ready(self):
        with self.lock:
            if self.state == "new":
                self.loading = True
                try:
                    self._load()
                finally:
                    self.loading = False
            return self.state == "ready"

    def process(self, text):
        """Текст -> текст с «+» перед ударными гласными. None — ударения недоступны (текст не менялся)."""
        if has_manual_stress(text):
            return text                  # пользователь расставил сам
        if not self.ready():
            return None
        out = []
        for i, part in enumerate(_SENT_SPLIT.split(text)):
            if i % 2 or not part.strip():     # разделители и пустое — как есть
                out.append(part)
                continue
            out.append(self._sentence(part))
        return "".join(out)

    def _sentence(self, s):
        hit = self.cache.get(s)
        if hit is not None:
            self.cache.move_to_end(s)
            return hit
        try:
            with self.lock:
                res = self.model.process_all(s)
            if not isinstance(res, str) or not res.strip():
                res = s
        except Exception as e:           # баги библиотеки на отдельных предложениях не должны ронять озвучку
            self.log(f"RUAccent не обработал предложение, оставляю без ударений ({type(e).__name__})")
            res = s
        self.cache[s] = res
        if len(self.cache) > 3000:
            self.cache.popitem(last=False)
        return res


# ------------------------------------------------------------ автоопределение формата
# (слово с ударением на 2-м слоге, то же с ударением на 1-м) — у этих слов смена ударения меняет фонемы
_PROBES = [("зам+ок", "з+амок"), ("мук+а", "м+ука"), ("дух+и", "д+ухи")]


def detect_mark_mode(phonemize):
    """phonemize(текст) -> плоский список фонем espeak. Возвращает формат пометок, который espeak реально учитывает,
    или None. Формат считается рабочим, если разное положение метки даёт разные фонемы, а лишних фонем (чтения «плюс») нет."""
    for mode in MARKS:
        good = 0
        for second, first in _PROBES:
            try:
                p2, p1 = phonemize(to_marks(second, mode)), phonemize(to_marks(first, mode))
                plain = phonemize(strip_marks(first))
            except Exception:
                break
            if "ˈ" not in p1 or "ˈ" not in p2 or not plain:
                continue
            if p1 != p2 and p1.index("ˈ") != p2.index("ˈ") and abs(len(p1) - len(plain)) <= 1 and abs(len(p2) - len(plain)) <= 1:
                good += 1
        if good >= 2:
            return mode
    return None


# ------------------------------------------------------------ запасной режим: ударение в фонемах
# качество гласной по букве: ударная (полная) и безударная (редуцированная, как у espeak)
_FULL = {"а": "a", "я": "a", "о": "o", "ё": "o", "у": "u", "ю": "u", "ы": "ɨ", "э": "ɛ", "е": "e", "и": "i"}
_REDUCED = {"а": "ɐ", "о": "ɐ", "я": "ɪ", "е": "ɪ", "э": "ɪ", "и": "ɪ"}
_REDUCED_PHONEMES = {"ɐ", "ə", "ɪ", "ᵻ"}


def retarget_stress(phonemes, word_plus):
    """Переносит знак ударения «ˈ» в фонемах одного слова на гласную, которую указал RUAccent, и меняет качество
    затронутых гласных (новая ударная — полная, прежняя ударная — редуцированная). Приблизительно: это запасной режим.
    Если число гласных в буквах и в фонемах не совпало — слово не трогаем (лучше стандартное ударение espeak, чем ошибка)."""
    pos = word_plus.find("+")
    if pos < 0 or word_plus.count("+") != 1:
        return list(phonemes)
    letters = word_plus.replace("+", "")
    vowel_letters = [ch.lower() for ch in letters if ch in RU_VOWELS]
    which = sum(1 for ch in word_plus[:pos] if ch in RU_VOWELS)   # номер ударной гласной по счёту
    old_marks = [i for i, p in enumerate(phonemes) if p == "ˈ"]
    base = [p for p in phonemes if p != "ˈ"]
    vowel_idx = [i for i, p in enumerate(base) if p and p[0] in IPA_VOWELS]
    if len(vowel_idx) != len(vowel_letters) or which >= len(vowel_idx):
        return list(phonemes)
    old_k = None
    if old_marks:                       # какая по счёту гласная была ударной у espeak
        after = old_marks[0] - sum(1 for i in old_marks if i < old_marks[0])
        old_k = next((k for k, i in enumerate(vowel_idx) if i >= after), None)
    if old_k == which:
        return list(phonemes)           # espeak и так поставил ударение туда же
    new_i = vowel_idx[which]
    if base[new_i] in _REDUCED_PHONEMES:
        base[new_i] = _FULL.get(vowel_letters[which], base[new_i])
    if old_k is not None and vowel_letters[old_k] in _REDUCED:
        base[vowel_idx[old_k]] = _REDUCED[vowel_letters[old_k]]
    base.insert(new_i, "ˈ")
    return base


def split_words(phonemes):
    """Список фонем предложения -> список слов (по пробелам)."""
    out, cur = [], []
    for ph in phonemes:
        if ph == " ":
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(ph)
    if cur:
        out.append(cur)
    return out


def apply_to_sentences(sentences, plain_text, plus_text):
    """sentences — результат voice.phonemize(plain_text) (список предложений-списков фонем).
    Возвращает такой же список, но с ударениями из plus_text; None, если слова не удалось сопоставить."""
    words_plus = russian_words(plus_text)
    chunks = [split_words(s) for s in sentences]
    if sum(len(c) for c in chunks) != len(words_plus) or len(russian_words(plain_text)) != len(words_plus):
        return None
    i, out = 0, []
    for sent in chunks:
        new = []
        for w in sent:
            new.append(retarget_stress(w, words_plus[i]) if "+" in words_plus[i] else w)
            i += 1
        flat = []
        for j, w in enumerate(new):
            if j:
                flat.append(" ")
            flat.extend(w)
        out.append(flat)
    return out


# ------------------------------------------------------------ запасной режим: озвучка по фонемам
def phoneme_chunks(voice, text, plus):
    """Генератор int16-байт по предложениям с ударениями из plus (RUAccent). None — слова не удалось сопоставить
    (тогда вызывающий читает обычным способом). Нужен Piper >= 1.3 (phonemize / phonemes_to_ids / phoneme_ids_to_audio)."""
    import numpy as np
    sentences = apply_to_sentences(voice.phonemize(text), text, plus)
    if sentences is None:
        return None

    def gen():
        rate = int(voice.config.sample_rate)
        gap = b"\x00\x00" * int(rate * 0.15)
        for i, phs in enumerate(sentences):
            a = np.asarray(voice.phoneme_ids_to_audio(voice.phonemes_to_ids(phs)))
            if a.dtype.kind == "f":
                a = a if float(np.max(np.abs(a)) if a.size else 0.0) <= 1.5 else a / 32768.0
                a = (np.clip(a, -1.0, 1.0) * 32767.0).astype(np.int16)
            if i:
                yield gap
            yield a.astype(np.int16).reshape(-1).tobytes()
    return gen()


class PiperAccents:
    """Ударения для голосов Piper в Twitch-TTS. Настройки читаются из config.json на лету:
    accent_on (true), accent_model ("tiny2"), accent_mark ("auto"), accent_dictionary (true),
    accent_light (true — tiny_mode: ~80 МБ вместо ~1,7 ГБ; слова с одной гласной ударение получают от espeak)."""

    def __init__(self, cfg, workdir, log):
        self.cfg, self.workdir, self.log = cfg, workdir, log
        self._acc = None
        self._key = None
        self._lock = threading.Lock()
        self._modes = {}          # id(voice) -> формат пометок

    def _accentizer(self):
        key = (str(self.cfg.get("accent_model") or MODEL), bool(self.cfg.get("accent_dictionary", True)),
               bool(self.cfg.get("accent_light", True)))
        with self._lock:
            if self._acc is None or key != self._key:
                self._key = key
                self._acc = Accentizer(self.workdir, self.log, model=key[0], use_dictionary=key[1], tiny_mode=key[2])
            return self._acc

    def preload(self, wanted=lambda: True):
        """Загружает RUAccent в фоне сразу при запуске программы — к первой фразе всё уже готово.
        wanted() — нужны ли ударения вообще (например, есть ли голоса Piper)."""
        def work():
            try:
                if self.cfg.get("accent_on", True) and wanted():
                    self._accentizer().ready()
            except Exception as e:
                self.log(f"Ударения: предзагрузка не удалась ({type(e).__name__}: {e})")
        threading.Thread(target=work, daemon=True).start()

    def status(self):
        """Короткий текст для окна."""
        if not self.cfg.get("accent_on", True):
            return "Ударения: выключены"
        acc = self._acc
        if acc is None or acc.state == "new":
            return "Ударения: загрузятся при первой фразе" if not (acc and acc.loading) else "Ударения: загружаются…"
        if acc.loading:
            return "Ударения: загружаются…"
        if acc.state == "ready":
            return f"Ударения: готовы (модель {acc.model_used})"
        return "Ударения: недоступны (см. журнал)"

    def _mode(self, voice):
        forced = str(self.cfg.get("accent_mark", "auto"))
        if forced != "auto":
            return None if forced == "off" else forced
        k = id(voice)
        if k not in self._modes:
            mode = None
            try:
                if hasattr(voice, "phonemize"):
                    flat = lambda t: [ph for sent in voice.phonemize(t) for ph in sent]
                    mode = detect_mark_mode(flat)
                    if mode is None and hasattr(voice, "phonemes_to_ids") and hasattr(voice, "phoneme_ids_to_audio"):
                        mode = "phoneme"
            except Exception as e:
                self.log(f"Не удалось определить формат ударений для Piper: {type(e).__name__}: {e}")
            self._modes[k] = mode
            names = {"combining": "знак ударения над гласной", "upper": "ударная гласная заглавной", "plus": "знак «+»",
                     "phoneme": "перестановка в фонемах (запасной режим)", None: "не поддерживается"}
            self.log("Ударения в Piper: " + names.get(mode, str(mode)))
        return self._modes[k]

    def prepare(self, voice, text):
        """-> (текст для Piper, текст с «+» для запасного режима или None). При любых проблемах возвращает текст как есть."""
        if not self.cfg.get("accent_on", True):
            return text, None
        try:
            plus = self._accentizer().process(text)
            if plus is None:
                return text, None
            mode = self._mode(voice)
            if mode in MARKS:
                return to_marks(plus, mode), None
            if mode == "phoneme":
                return strip_marks(plus), plus
            return strip_marks(plus), None
        except Exception as e:
            self.log(f"Ударения не сработали ({type(e).__name__}: {e}) — читаю без них")
            return text, None


if __name__ == "__main__":
    # установщик: заранее скачать модели ударений, чтобы программа не качала их при первом запуске
    #   python accent.py --download <папка data/ruaccent> [модель]
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "--download":
        acc = Accentizer(sys.argv[2], lambda m: print(m, flush=True), model=sys.argv[3] if len(sys.argv) > 3 else MODEL)
        sys.exit(0 if acc.ready() else 1)
    print("Запуск: python accent.py --download <папка> [модель]")
    sys.exit(2)
