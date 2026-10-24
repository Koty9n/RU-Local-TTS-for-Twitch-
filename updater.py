"""Проверка новой версии на странице проекта (GitHub) и запуск самообновления.

Как это работает:
  1. check() спрашивает у GitHub последний релиз (api.github.com/.../releases/latest). Если релизов нет или API недоступен
     (лимит запросов) — читает version.txt из ветки main.
  2. Версии сравниваются по числам: «b1.3 (24.10.2026)» -> (1, 3). Если на GitHub версия больше — возвращается описание
     обновления, иначе None.
  3. start_update() копирует self_update.ps1 во временную папку и запускает его отдельным процессом. Скрипт ждёт, пока
     программа закроется, скачивает архив, заменяет код (config.json, data, голоса и venv не трогает) и запускает программу снова.

Модуль ничего не пишет на диск сам и не требует сторонних библиотек.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = "Koty9n/RU-Local-TTS-for-Twitch-"   # владелец/репозиторий (в названии на конце дефис — так и есть)
PAGE = f"https://github.com/{REPO}"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RAW_VERSION = f"https://raw.githubusercontent.com/{REPO}/main/version.txt"
ZIP_MAIN = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
USER_AGENT = "RU-Local-TTS-updater"
SCRIPT = "self_update.ps1"


class UpdateError(Exception):
    """Не удалось узнать, есть ли обновление (нет интернета, GitHub не ответил)."""


def parse_version(text):
    """'b1.3 (24.10.2026)' -> (1, 3); 'v2' -> (2,); непохоже на версию (например, тег 'TTS') -> None."""
    parts = (text or "").strip().split()
    if not parts:
        return None
    m = re.fullmatch(r"[vVbB]?(\d+(?:\.\d+)*)", parts[0])
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def local_version(base):
    """Первая строка version.txt рядом с программой ('' — файла нет)."""
    try:
        return (Path(base) / "version.txt").read_text(encoding="utf-8-sig").splitlines()[0].strip()
    except Exception:
        return ""


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8-sig", "replace")


def _latest_release(timeout):
    """Описание последнего релиза или None, если релизов нет / лимит API."""
    try:
        data = json.loads(_get(API_LATEST, timeout))
    except urllib.error.HTTPError as e:
        if e.code in (403, 404, 429):
            return None
        raise
    tag = data.get("tag_name") or ""
    if parse_version(tag) is None:
        return None
    zip_url = ""
    for a in data.get("assets") or []:   # архив, который автор приложил к релизу, надёжнее автоархива GitHub
        if str(a.get("name", "")).lower().endswith(".zip") and a.get("browser_download_url"):
            zip_url = a["browser_download_url"]
            break
    return {"version": data.get("name") or tag, "tag": tag, "url": zip_url or data.get("zipball_url") or "",
            "page": data.get("html_url") or PAGE + "/releases/latest", "notes": data.get("body") or ""}


def _latest_main(timeout):
    text = _get(RAW_VERSION, timeout).splitlines()
    first = text[0].strip() if text else ""
    if parse_version(first) is None:
        return None
    return {"version": first, "tag": first, "url": ZIP_MAIN, "page": PAGE, "notes": ""}


def latest(timeout=8):
    """Последняя версия на GitHub (dict) или UpdateError, если узнать не удалось."""
    try:
        info = _latest_release(timeout)
        if info is None:
            info = _latest_main(timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(f"{type(e).__name__}: {e}")
    if info is None or not info.get("url"):
        raise UpdateError("на странице проекта не нашлось версии")
    return info


def check(base, timeout=8):
    """Есть ли версия новее установленной. Возвращает dict (version, url, page, notes, current) или None.
    Бросает UpdateError, если проверить не удалось."""
    info = latest(timeout)
    cur_text = local_version(base)
    cur, new = parse_version(cur_text), parse_version(info["tag"]) or parse_version(info["version"])
    if new is None or (cur is not None and new <= cur):
        return None
    info["current"] = cur_text or "неизвестна"
    return info


def start_update(base, info, pid=None):
    """Запускает self_update.ps1 отдельным процессом и сразу возвращается. После этого программа должна закрыться."""
    if os.name != "nt":
        raise UpdateError("автообновление работает только в Windows")
    src = Path(base) / SCRIPT
    if not src.exists():
        raise UpdateError(f"нет файла {SCRIPT}")
    tmp = Path(tempfile.mkdtemp(prefix="TTS_update_"))
    script = tmp / SCRIPT   # запускаем копию: сам скрипт будет заменён вместе с остальными файлами
    shutil.copyfile(src, script)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script),
           "-Target", str(base), "-Url", info["url"], "-Version", str(info.get("version", "")),
           "-WaitPid", str(pid if pid is not None else os.getpid())]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) \
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(cmd, creationflags=flags, close_fds=True, cwd=str(tmp))
