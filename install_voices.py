"""Скачивает голоса Piper с piperhub.org (источник — репозиторий rraaww/ru_piper на Hugging Face) в папку voices.

Имя в TTS -> ключ поиска файла в репозитории:
  IGM -> igm3804, Mari -> mari, Women -> fr6800, Сказочник -> sushkov-v4
Ничего не перекачивает, если голос уже стоит. Запуск:  python install_voices.py [папка_voices] [имя ...]
Код возврата 0, если все голоса на месте (остальное печатает причину и продолжает).
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "rraaww/ru_piper"
VOICES = [("IGM", "igm3804"), ("Mari", "mari"), ("Women", "fr6800"), ("Сказочник", "sushkov-v4")]
UA = {"User-Agent": "TwitchTTS-installer"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def http(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def list_files(repo=REPO):
    """Все файлы репозитория (рекурсивно) через публичный API Hugging Face."""
    for kind in ("models", "datasets"):
        try:
            with http(f"https://huggingface.co/api/{kind}/{repo}/tree/main?recursive=true") as r:
                items = json.load(r)
            files = [i["path"] for i in items if i.get("type") == "file"]
            if files:
                return kind, files
        except Exception:
            continue
    raise RuntimeError("не удалось получить список файлов репозитория " + repo)


def pick(files, key):
    """(onnx, json) для ключа: ищем .onnx с ключом в пути, предпочитаем 'medium' и самый короткий путь."""
    k = norm(key)
    onnx = [f for f in files if f.lower().endswith(".onnx") and k in norm(f)]
    onnx.sort(key=lambda f: ("medium" not in f.lower(), len(f)))
    for o in onnx:
        if o + ".json" in files:
            return o, o + ".json"
    return None


def download(kind, repo, path, dest):
    prefix = "" if kind == "models" else "datasets/"
    url = f"https://huggingface.co/{prefix}{repo}/resolve/main/{urllib.parse.quote(path)}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    with http(url, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    tmp.replace(dest)


def main(out_dir, only=None):
    """only — имена голосов, которые нужны (выбор в окне); None — все."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wanted = [(n, k) for n, k in VOICES if only is None or n in only]
    todo = [(n, k) for n, k in wanted if not ((out / f"{n}.onnx").exists() and (out / f"{n}.onnx.json").exists())]
    if not todo:
        print("Выбранные голоса уже установлены.")
        return 0
    try:
        kind, files = list_files()
    except Exception as e:
        print("ОШИБКА:", e)
        return 1
    def one(name, key):
        """-> True, если голос скачан. Голоса качаются параллельно (по потоку на голос)."""
        found = pick(files, key)
        if not found:
            print(f"[{name}] в репозитории не найден файл с '{key}' — пропускаю", flush=True)
            return False
        try:
            print(f"[{name}] скачиваю {found[0]} ...", flush=True)
            download(kind, REPO, found[1], out / f"{name}.onnx.json")
            json.loads((out / f"{name}.onnx.json").read_text(encoding="utf-8"))
            download(kind, REPO, found[0], out / f"{name}.onnx")
            if (out / f"{name}.onnx").stat().st_size < 1_000_000:
                raise RuntimeError("файл модели слишком маленький")
            print(f"[{name}] готово", flush=True)
            return True
        except Exception as e:
            print(f"[{name}] ошибка: {type(e).__name__}: {e}", flush=True)
            for ext in (".onnx", ".onnx.json"):
                (out / f"{name}{ext}").unlink(missing_ok=True)
            return False

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda nk: one(*nk), todo))
    return 0 if all(results) else 1


if __name__ == "__main__":
    # python install_voices.py [папка_voices] [имя ...]  — без имён качаются все
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "voices",
                  set(sys.argv[2:]) or None))
