"""Воркер движка TeraTTS (русская GLaDOS). Запускается ОТДЕЛЬНЫМ процессом (из venv, у старых установок — из venv_tera).

Протокол (stdin/stdout, построчно JSON):
  воркер -> {"ready": true, "accent": "<модель ударений или null>"} | {"error": "..."}
  программа -> {"text": "...", "ls": 1.1}
  воркер -> несколько кадров, по одному на предложение:
            {"rate": 22050, "n": <байт>, "more": true|false}\\n + n байт int16 PCM
         или {"error": "..."}
Всё, что библиотеки печатают в stdout, уходит в stderr (data/tera_worker.log), чтобы не ломать протокол.

Режим проверки:  python tera_worker.py <модель> <модель_ударений> --warmup
"""
import json
import os
import re
import sys
import time
import traceback

# Ударения для имён, которые ruaccent произносит неверно (из репозитория KPEKEP/GLaDOS)
CUSTOM_DICT = {
    "ГЛаДОС": "ГЛ+А+ДОС",
    "ГЛАДОС": "ГЛ+АДОС",
    "ГлаДОС": "Гл+аДОС",
    "ИИ": "+И-+И",
    "АИ": "+А-+И",
}
# Свой словарь ударений: data/stress_dict.txt (воркер стартует из data/tera, поэтому ../stress_dict.txt).
# Строка:  слово=сл+ово   (плюс перед ударной гласной; # — комментарий). Правится в блокноте, применяется при
# следующем запуске движка (или кнопкой «Перезапустить» / перезапуском программы).
USER_DICT_FILES = ["../stress_dict.txt", "stress_dict.txt"]


def load_user_dict():
    out = {}
    for rel in USER_DICT_FILES:
        try:
            with open(rel, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.split("#", 1)[0].strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k and v:
                            out[k.lower()] = v.lower()
        except OSError:
            pass
    return out


USER_DICT = load_user_dict()
# Режим буквы «р»: off — как есть; double — «р» между гласными/после гласной удваивается (длиннее и чётче).
R_FIX = os.environ.get("TTS_R_FIX", "off").strip().lower()
# Лёгкий режим (accent_light): ruaccent в tiny_mode и GLaDOS без своего словаря — ~0,35 ГБ памяти вместо ~2,3 ГБ.
# Ударения в простых словах (одна гласная, «ё») тогда ставит add_simple_stress.
LIGHT = os.environ.get("TTS_ACCENT_LIGHT", "1").strip() != "0"


def apply_user_dict(text):
    for k, v in USER_DICT.items():
        text = re.sub(r"(?<![\w+])" + re.escape(k) + r"(?![\w+])", v, text, flags=re.IGNORECASE)
    return text


def fix_r(text):
    if R_FIX != "double":
        return text
    # «р» после гласной (с возможным знаком ударения) и перед согласной/концом слова — удваиваем: «мир» -> «мирр»
    return re.sub(r"(?<=[аеёиоуыэюя+])р(?=[бвгджзйклмнпстфхцчшщь]|\b)", "рр", text)


# безударные служебные слова с одной гласной — им «+» не ставим
UNSTRESSED = {"без", "в", "во", "для", "до", "за", "из", "к", "ко", "на", "над", "о", "об", "от", "по", "под",
              "при", "про", "с", "со", "у", "через", "и", "а", "но", "же", "ж", "ли", "ль", "бы", "б", "не", "ни"}
# безударные частицы после дефиса: «что-то», «скажи-ка», «ну-тка»
POSTFIX = {"то", "ка", "де", "тка", "с"}
_SIMPLE_WORD_RE = re.compile(r"[а-яё+]+(?:-[а-яё+]+)*", re.IGNORECASE)
# ruaccent стирает «+», расставленные CUSTOM_DICT до него («+А-+И» -> «а-и») — возвращаем
RESTORE = {v.lower().replace("+", ""): v.lower() for v in CUSTOM_DICT.values()}
# из словаря GLaDOS в лёгком режиме оставляем только то, что без него звучит иначе, чем при обучении модели
LIGHT_DIC = {"и": "y0", "же": "zh i0"}


def _simple_part(w, after_hyphen):
    if "+" in w or (after_hyphen and w.lower() in POSTFIX):
        return w
    if "ё" in w.lower():
        return re.sub("([ёЁ])", r"+\1", w, count=1)
    vowels = [i for i, ch in enumerate(w) if ch.lower() in "аеиоуыэюя"]
    if len(vowels) == 1 and w.lower() not in UNSTRESSED:
        return w[:vowels[0]] + "+" + w[vowels[0]:]
    return w


def add_simple_stress(text):
    """Без словаря GLaDOS читает слово без «+» совсем без ударения. tiny_mode у ruaccent не размечает слова
    с одной гласной, поэтому ставим сами: «+» перед «ё» и перед единственной гласной (кроме служебных слов)."""
    def word(m):
        w = m.group()
        if "+" not in w and w.lower() in RESTORE:
            return RESTORE[w.lower()]
        return "-".join(_simple_part(p, i > 0) for i, p in enumerate(w.split("-")))
    return _SIMPLE_WORD_RE.sub(word, text)


def final_text(text):
    """Последний шаг перед моделью: ударения уже расставлены. Модель обучена на строчном тексте — заглавные
    буквы (в том числе «Р» в начале слова) она может читать неверно, поэтому приводим к нижнему регистру."""
    return fix_r(text.lower())


# Порядок запасных моделей ударений, если выбранная не подошла к установленной версии ruaccent
ACCENT_FALLBACK = ["tiny2", "tiny", "turbo3.1", "turbo3"]
TEST_PHRASE = "Привет, замок на двери."
UNKNOWN_PROBE = "имба"    # слова нет в словаре RUAccent — проверяет нейросеть ударений для незнакомых слов


def log(*a):
    print("[tera]", *a, file=sys.stderr, flush=True)


LATIN_EXTRA = str.maketrans({"w": "в", "W": "В", "q": "к", "Q": "К", "x": "кс", "X": "Кс"})


def prepare(text):
    """Латиница -> кириллица, цифры -> слова."""
    # transliterate не знает w, q, x — без замены GLaDOS их просто пропускает («xbox» -> «боо»)
    text = text.translate(LATIN_EXTRA)
    try:
        from transliterate import translit
        text = translit(text, "ru")
    except Exception:
        pass
    try:
        from num2words import num2words
        text = re.sub(r"\d{1,12}", lambda m: num2words(int(m.group()), lang="ru"), text)
    except Exception:
        pass
    for k, v in CUSTOM_DICT.items():
        text = text.replace(k, v)
    text = apply_user_dict(text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text, maxlen=90):
    """Режет на короткие куски, чтобы первый начал звучать раньше, чем досчитается остальное."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out, cur = [], ""
    for p in parts:
        # склеиваем только совсем короткие обрывки («Привет!»), иначе каждое предложение — отдельный кусок
        if cur and (len(cur) >= 30 or len(cur) + len(p) + 1 > maxlen):
            out.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        out.append(cur)
    final = []
    for s in out:
        while len(s) > maxlen * 1.6:
            i = max(s.rfind(",", 0, maxlen + 20), s.rfind(" ", 0, maxlen + 20))
            i = i if i > 20 else maxlen
            final.append(s[:i + 1].strip(" ,"))
            s = s[i + 1:].strip()
        if s:
            final.append(s)
    return final


def to_int16(audio):
    import numpy as np
    if hasattr(audio, "detach"):  # torch.Tensor
        audio = audio.detach().cpu().numpy()
    a = np.asarray(audio).reshape(-1)
    if a.dtype == np.int16:
        return a
    a = a.astype(np.float32)
    peak = float(np.abs(a).max()) if a.size else 0.0
    if peak > 1.5:  # уже в «целых» единицах
        return np.clip(a, -32768, 32767).astype(np.int16)
    return (np.clip(a, -1.0, 1.0) * 32767).astype(np.int16)


def load_accentizer(preferred):
    """Возвращает (ruaccent, имя_модели) или (None, None). Каждую модель проверяем на реальной фразе:
    так ловится несовпадение версий (например «Required inputs ['token_type_ids'] are missing»)."""
    import inspect
    try:   # путь с русскими буквами ломает часть ruaccent (pycrfsuite) — подменяем путь на латинский
        import ascii_paths
        ascii_paths.patch_pycrfsuite()
    except Exception as e:
        log(f"ascii_paths: {type(e).__name__}: {e}")
    from ruaccent import RUAccent
    # модели ударений — в общей папке data/ruaccent (её же берут голоса Piper): качаются один раз, а не дважды
    workdir = os.path.abspath(os.path.join("..", "ruaccent"))
    os.makedirs(workdir, exist_ok=True)
    sizes = [preferred] + [s for s in ACCENT_FALLBACK if s != preferred]
    for size in sizes:
        try:
            acc = RUAccent(workdir=workdir) if "workdir" in inspect.signature(RUAccent.__init__).parameters else RUAccent()
            # ruaccent ищет слова строчными: ключи вроде «ГЛаДОС» иначе не срабатывают
            custom = {k.lower(): v.lower() for k, v in CUSTOM_DICT.items()}
            kw = {"omograph_model_size": size, "use_dictionary": True, "custom_dict": {**custom, **USER_DICT}}
            if "workdir" in inspect.signature(acc.load).parameters:
                kw["workdir"] = workdir
            if LIGHT and "tiny_mode" in inspect.signature(acc.load).parameters:
                kw["tiny_mode"] = True   # без огромного словаря в памяти: ~80 МБ вместо ~1,7 ГБ
            acc.load(**kw)
            acc.process_all(TEST_PHRASE)
            log(f"ударения: модель '{size}' работает")
            try:
                acc.process_all(UNKNOWN_PROBE)
            except Exception as e:
                log(f"ВНИМАНИЕ: ударения не работают для слов не из словаря ({type(e).__name__}: {e}) — "
                    "фразы со сленгом прочитаются без ударений. Обычно лечится: pip install \"transformers<5\"")
            return acc, size
        except Exception as e:
            log(f"ударения: модель '{size}' не подошла: {type(e).__name__}: {e}")
    log("ударения ОТКЛЮЧЕНЫ: ни одна модель ruaccent не заработала (голос будет звучать, но с ошибками ударений)")
    return None, None


def run_variants(synth_part, rate):
    """Проверка на слух: одни и те же фразы в нескольких вариантах -> data/glados_test/*.wav"""
    global R_FIX
    import wave
    out = os.path.abspath(os.path.join("..", "glados_test"))
    os.makedirs(out, exist_ok=True)
    phrases = ["Привет, рыба! Тебе ровно три рубля.", "Ракета, барьер, мир, горит."]
    for mode in ("off", "double"):
        R_FIX = mode
        for ls in (1.0, 1.1, 1.2):
            for i, ph in enumerate(phrases, 1):
                pcm = b"".join(synth_part(p, ls) for p in split_sentences(prepare(ph)))
                name = os.path.join(out, f"r-{mode}_ls{ls}_{i}.wav")
                with wave.open(name, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    log("готово: " + out)
    return 0


def main():
    out = sys.stdout.buffer
    sys.stdout = sys.stderr  # чтобы print() из библиотек не попадал в протокол

    def send(obj, payload=b""):
        out.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        if payload:
            out.write(payload)
        out.flush()

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    model = args[0] if args else "TeraTTS/glados2-g2p-vits"
    accent_pref = args[1] if len(args) > 1 else "tiny2"
    warmup = "--warmup" in sys.argv

    try:   # потоки и приоритет — до загрузки моделей (настройки cpu_threads/low_priority из config.json)
        import ort_tune
        ort_tune.apply_from_env()
    except Exception as e:
        log(f"ort_tune: {type(e).__name__}: {e}")

    try:
        t0 = time.time()
        from TeraTTS import TTS
        accentizer, accent_used = load_accentizer(accent_pref)
        light = LIGHT and accentizer is not None   # без ruaccent словарь GLaDOS — единственный источник ударений
        tts = TTS(model, add_time_to_end=0.25, tokenizer_load_dict=not light)
        if light and isinstance(getattr(getattr(tts, "tokenizer", None), "dic", None), dict):
            tts.tokenizer.dic.update(LIGHT_DIC)
        log(f"загрузка заняла {time.time() - t0:.1f} с")
    except Exception:
        send({"error": "Не удалось загрузить TeraTTS/ruaccent:\n" + traceback.format_exc()[-1500:]})
        return 1

    rate_default = 22050
    for attr in ("sample_rate", "samplerate", "sr"):
        v = getattr(tts, attr, None)
        if isinstance(v, int) and v > 8000:
            rate_default = v
            break

    def synth_part(part, ls):
        t1 = time.time()
        if accentizer is not None:
            try:
                part = accentizer.process_all(part)
            except Exception as e:  # сбой ударений на конкретной фразе — не роняем озвучку
                log(f"ударения не сработали на фразе: {type(e).__name__}: {e}")
            if light:
                part = add_simple_stress(part)
        t2 = time.time()
        part = final_text(part)
        try:
            audio = tts(part, play=False, lenght_scale=ls)  # опечатка lenght_scale — как в библиотеке
        except TypeError:
            audio = tts(part, lenght_scale=ls)
        pcm = to_int16(audio).tobytes()
        t3 = time.time()
        log(f"ударения {t2 - t1:.2f} с, синтез {t3 - t2:.2f} с, звук {len(pcm) / 2 / rate_default:.2f} с | {part[:40]}")
        return pcm

    def synth_stream(text, ls):
        parts = split_sentences(prepare(text))
        if not parts:
            send({"rate": rate_default, "n": 0, "more": False})
            return
        for i, part in enumerate(parts):
            pcm = synth_part(part, ls)
            send({"rate": rate_default, "n": len(pcm), "more": i < len(parts) - 1}, pcm)

    if "--variants" in sys.argv:
        return run_variants(synth_part, rate_default)

    if warmup:
        try:
            t = time.time()
            parts = split_sentences(prepare("Привет. Это проверка голоса. Сегодня двадцать пять градусов."))
            total = sum(len(synth_part(p, 1.1)) for p in parts)
            if not total:
                raise RuntimeError("модель вернула пустой звук")
            log(f"проверка пройдена за {time.time() - t:.1f} с")
            send({"ready": True, "accent": accent_used, "n": total})
            return 0
        except Exception:
            send({"error": traceback.format_exc()[-1500:]})
            return 1

    send({"ready": True, "accent": accent_used})
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        try:
            req = json.loads(line)
            text = str(req.get("text", "")).strip()
            synth_stream(text, float(req.get("ls", 1.1))) if text else send(
                {"rate": rate_default, "n": 0, "more": False})
        except Exception as e:
            send({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    sys.exit(main())
