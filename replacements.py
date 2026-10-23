"""Словарь замен перед озвучкой: «minecraft = майнкрафт», «gg = гэгэ», «😂 = ахаха».

Файлы: data/replacements.txt (свой, правится в панели OBS) + готовые data/replacements_*.txt (заготовки).
Свои строки важнее заготовок. Формат строки:  что = на что   (# — комментарий, регистр не важен).
Нагрузка: весь словарь — одно регулярное выражение, текст проходится за один раз; файлы перечитываются,
только когда поменялась дата изменения.
"""
import re
import time
from pathlib import Path

from sounds import SND, to_marks

SOUND_ONLY = re.compile(r"^\[([^\[\]]{1,40})\]$")   # значение строки — только звук: «kekw = [смех]»
# эмодзи и служебные символы к ним (вариант, склейка, флаги, цвет кожи)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣]+")
HEAD = ("# Словарь замен перед озвучкой. Строка:  что = на что   (# — комментарий, регистр не важен)\n"
        "# Слова заменяются только целиком: «gg» не тронет «eggs». Эмодзи — где угодно в тексте.\n"
        "# Эти строки важнее готового словаря replacements_twitch.txt. Чтобы слово НЕ заменялось: gg = gg\n"
        "# Звук вместо слова: kekw = [смех]  (проще — в панели OBS на вкладке «Звуки»)\n")


def _edge(ch, start):
    """Граница для края ключа: буква/цифра — не внутри слова; ASCII-символ («+», «:)») — отдельно стоящий;
    эмодзи — где угодно."""
    if re.match(r"\w", ch):
        return r"(?<!\w)" if start else r"(?!\w)"
    if ord(ch) < 128:
        return r"(?<!\S)" if start else r"(?!\S)"
    return ""


def _norm_key(k):
    return re.sub(r"\s+", " ", k.strip().lower())


def check_key(word):
    """Слово из чата для строки словаря; без символов, которые ломают формат строки."""
    key = _norm_key(word)
    if not key or any(c in key for c in "=#[]\x01"):
        raise ValueError("Слово не подходит: нужно без «=», «#» и скобок")
    return key


class Replacements:
    def __init__(self, path, log=print):
        self.path = Path(path)
        self.log = log
        if not self.path.exists():
            self.path.write_text(HEAD, encoding="utf-8")
        self.map, self.rx, self._seen = {}, None, None
        self._checked = time.monotonic()
        self.load()

    def _files(self):
        extra = sorted(p for p in self.path.parent.glob("replacements_*.txt") if p != self.path)
        return extra + [self.path]          # свой файл последним — его строки перекрывают заготовки

    def _stamp(self):
        out = []
        for f in self._files():
            try:
                out.append((f.name, f.stat().st_mtime_ns))
            except OSError:
                pass
        return out

    def load(self):
        m = {}
        for f in self._files():
            try:
                lines = f.read_text(encoding="utf-8-sig").splitlines()
            except OSError:
                continue
            for line in lines:
                if line.lstrip().startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = _norm_key(k)
                if k:
                    m[k] = to_marks(v.split(" #", 1)[0].strip())   # «[смех]» -> метка звука
        parts = []
        for k in sorted(m, key=len, reverse=True):   # длинные раньше: «gg wp» важнее «gg»
            body = r"\s+".join(re.escape(w) for w in k.split(" "))
            parts.append(_edge(k[0], True) + body + _edge(k[-1], False))
        self.map = m
        self.rx = re.compile("|".join(parts), re.IGNORECASE) if parts else None
        self._seen = self._stamp()
        # какие слова своего словаря — «чистый» звук (kekw = [смех]): их показывает панель у каждого звука
        self.sound_keys = {}
        for k, v in self._own_lines():
            sm = SOUND_ONLY.match(v)
            if sm:
                self.sound_keys.setdefault(sm.group(1).strip().lower(), []).append(k)

    def _own_lines(self):
        """(ключ, значение) из своего файла, без комментариев."""
        out = []
        for line in self.get_text().splitlines():
            if line.lstrip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if _norm_key(k):
                out.append((_norm_key(k), v.split(" #", 1)[0].strip()))
        return out

    def sound_words(self, name):
        self._fresh()
        return self.sound_keys.get(str(name).lower(), [])

    def _rewrite(self, keep, add=""):
        """Свой файл: оставить строки, для которых keep(ключ, значение) истинно, и дописать add."""
        lines = []
        for line in self.get_text().splitlines():
            if not line.lstrip().startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if _norm_key(k) and not keep(_norm_key(k), v.split(" #", 1)[0].strip()):
                    continue
            lines.append(line)
        if add:
            lines.append(add)
        self.set_text("\n".join(lines))

    def set_sound(self, word, name):
        """«kekw = [смех]» в свой словарь; старая строка для того же слова заменяется."""
        key = check_key(word)
        self._rewrite(lambda k, v: k != key, f"{key} = [{name}]")
        return key

    def drop_sound(self, name):
        """Убрать строки «слово = [имя]» (строки вроде «гол = гол [имя]» не трогаем)."""
        n = str(name).lower()
        self._rewrite(lambda k, v: not (SOUND_ONLY.match(v) and SOUND_ONLY.match(v).group(1).strip().lower() == n))

    def _fresh(self):
        now = time.monotonic()
        if now - self._checked > 2:           # дату файлов смотрим не чаще раза в 2 с
            self._checked = now
            if self._stamp() != self._seen:   # файл правили — подхватываем без перезапуска
                try:
                    self.load()
                except Exception as e:
                    self._seen = self._stamp()
                    self.log(f"Словарь замен не прочитался: {e}")

    def apply(self, text, strip_emoji=True):
        self._fresh()
        text = text.replace(SND, " ")         # звук зритель вызывает только словами из словаря
        if self.rx is not None:
            text = self.rx.sub(self._sub, text)
        if strip_emoji:
            text = EMOJI_RE.sub(" ", text)
        return re.sub(r"\s+([,.!?…])", r"\1", re.sub(r"\s+", " ", text)).strip()

    def _sub(self, mt):
        g = mt.group()
        new = self.map.get(_norm_key(g), g)
        # эмодзи прилипают к словам («привет😂») — отделяем пробелами; слова не трогаем («Telegram-канал»)
        return new if re.match(r"[\w\x00-\x7f]", g) else f" {new} "

    # ---- для панели: свой файл целиком
    def get_text(self):
        try:
            return self.path.read_text(encoding="utf-8-sig")
        except OSError:
            return HEAD

    def set_text(self, text):
        text = str(text or "").replace("\r\n", "\n")
        if not text.lstrip().startswith("#"):
            text = HEAD + text
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        tmp.replace(self.path)
        self.load()
        return len(self.map)
