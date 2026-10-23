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

# эмодзи и служебные символы к ним (вариант, склейка, флаги, цвет кожи)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣]+")
HEAD = ("# Словарь замен перед озвучкой. Строка:  что = на что   (# — комментарий, регистр не важен)\n"
        "# Слова заменяются только целиком: «gg» не тронет «eggs». Эмодзи — где угодно в тексте.\n"
        "# Эти строки важнее готового словаря replacements_twitch.txt. Чтобы слово НЕ заменялось: gg = gg\n"
        "# Звук вместо слова: kekw = [смех]  (звуки добавляются в панели OBS: «Словарь» → «Звуки»)\n")


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

    def apply(self, text, strip_emoji=True):
        now = time.monotonic()
        if now - self._checked > 2:           # дату файлов смотрим не чаще раза в 2 с
            self._checked = now
            if self._stamp() != self._seen:   # файл правили — подхватываем без перезапуска
                try:
                    self.load()
                except Exception as e:
                    self._seen = self._stamp()
                    self.log(f"Словарь замен не прочитался: {e}")
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
