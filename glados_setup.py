"""Установка движка GLaDOS (TeraTTS) прямо из приложения — кнопка «Установить GLaDOS» (обычно её ставит install.ps1).

Что делает: ставит TeraTTS и ruaccent в venv программы (если venv нет — находит Python 3.10–3.12 и создаёт venv_tera)
-> скачивает модели и проверяет голос (data/tera). Всё идёт в фоне, ход установки виден в журнале и на вкладке «Голоса».
Если подходящего Python нет, ничего не ставит сам — просит разрешения (state == "need_python"), потом может
поставить его через winget.
"""
import os
import subprocess
import threading
import time
from pathlib import Path

MODEL = "TeraTTS/glados2-g2p-vits"
PY_OK = {"3.10", "3.11", "3.12"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


ENVS = ("venv", "venv_tera")   # с v3.7 всё ставится в общий venv; venv_tera — от старых установок


def _env_python(root, name):
    for rel in (f"{name}/Scripts/python.exe", f"{name}/bin/python"):
        if (Path(root) / rel).exists():
            return Path(root) / rel
    return None


def _has_tera(root, name):
    env = Path(root) / name
    return any(env.glob("Lib/site-packages/TeraTTS")) or any(env.glob("lib/python*/site-packages/TeraTTS"))


def engine_python(root):
    """python.exe окружения, где реально стоит TeraTTS (общий venv важнее старого venv_tera), иначе None."""
    for name in ENVS:
        py = _env_python(root, name)
        if py is not None and _has_tera(root, name):
            return py
    return None


def venv_python(root):
    """Куда ставить движок: общий venv программы, а если его нет — отдельный venv_tera (как раньше)."""
    return _env_python(root, "venv") or _env_python(root, "venv_tera")


MODEL_FILE = Path("data/tera/model/TeraTTS/glados2-g2p-vits/exported/model.onnx")


def engine_installed(root):
    """Движок реально установлен: есть пакет TeraTTS И скачана модель. Без модели голос не показываем —
    иначе первая же фраза GLaDOS молча скачала бы ~565 МБ (например, если GLaDOS не выбрали при установке)."""
    return engine_python(root) is not None and (Path(root) / MODEL_FILE).exists()


class GladosInstaller:
    """state: idle | installing | need_python | done | failed. step — короткий текст для окна."""

    def __init__(self, base, data, log, accent="tiny2", runner=None):
        self.base, self.data, self.log = Path(base), Path(data), log
        self.accent = accent
        self.state = "idle"
        self.step = ""
        self.thread = None
        self.on_done = None
        self._run = runner or self._real_run      # runner подменяется в тестах

    # ---- запуск
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self, allow_winget=False, on_done=None):
        if self.running():
            return
        self.on_done = on_done
        self.state, self.step = "installing", "подготовка…"
        self.thread = threading.Thread(target=self._main, args=(allow_winget,), daemon=True)
        self.thread.start()

    def _main(self, allow_winget):
        ok = False
        try:
            ok = self._install(allow_winget)
            if self.state == "installing":
                self.state = "done" if ok else "failed"
        except Exception as e:
            self.log(f"GLaDOS: установка не удалась: {type(e).__name__}: {e}")
            self.state, self.step = "failed", f"ошибка: {e}"
        finally:
            if self.on_done:
                try:
                    self.on_done(self.state == "done")
                except Exception:
                    pass

    # ---- шаги
    def _install(self, allow_winget):
        worker = self.base / "tera_worker.py"
        if not worker.exists():
            self.log("GLaDOS: рядом с программой нет tera_worker.py — установка невозможна")
            self.step = "нет файла tera_worker.py"
            return False
        logf = self.data / "glados_install.log"
        self.data.mkdir(exist_ok=True)

        py = venv_python(self.base)
        if py is None:
            self.step = "1/4 ищу Python 3.10–3.12…"
            sys_py = self.find_python()
            if sys_py is None and allow_winget:
                sys_py = self._winget_python(logf)
            if sys_py is None:
                self.state, self.step = "need_python", "нужен Python 3.12"
                self.log("GLaDOS: не найден Python 3.10–3.12. Разреши установку Python (кнопка на вкладке «Голоса») "
                         "или поставь его сам: winget install Python.Python.3.12")
                return False
            self.step = "1/4 создаю окружение…"
            self.log("GLaDOS: создаю окружение venv_tera")
            if self._run(sys_py + ["-m", "venv", str(self.base / "venv_tera")], self.base, logf) != 0:
                return self._fail("не удалось создать окружение (venv_tera)")
            py = venv_python(self.base)
            if py is None:
                return self._fail("окружение создано без python")
        py = str(py)

        self.step = "2/4 обновляю pip…"
        self._run([py, "-m", "pip", "install", "--upgrade", "pip"], self.base, logf)
        self.step = "3/4 ставлю TeraTTS (несколько минут, ~1 ГБ)…"
        self.log("GLaDOS: ставлю TeraTTS и ruaccent — несколько минут, нужен интернет")
        if self._run([py, "-m", "pip", "install", "TeraTTS", "transliterate", "num2words", "transformers<5"], self.base, logf) != 0:
            return self._fail("pip не смог поставить TeraTTS (подробности в data/glados_install.log)")
        if self._run([py, "-m", "pip", "install", "--upgrade", "ruaccent", "transformers<5"], self.base, logf) != 0:
            return self._fail("pip не смог поставить ruaccent (подробности в data/glados_install.log)")

        self.step = "4/4 скачиваю модели и проверяю голос…"
        self.log("GLaDOS: скачиваю модели голоса и ударений, проверяю")
        wdir = self.data / "tera"
        wdir.mkdir(exist_ok=True)
        rc = self._run([py, "-X", "utf8", str(worker), MODEL, self.accent, "--warmup"], wdir, logf)
        if rc != 0:
            return self._fail("движок установился, но тест голоса не прошёл (см. data/glados_install.log)")
        self.step = "установлена"
        self.log("GLaDOS: готово — голос «glados» установлен")
        return True

    def _fail(self, text):
        self.step = text
        self.log("GLaDOS: " + text)
        return False

    # ---- поиск Python
    def find_python(self):
        cands = [["py", "-3.12"], ["py", "-3.11"], ["py", "-3.10"], ["python"], ["python3"]]
        local = os.environ.get("LOCALAPPDATA", "")
        for v in ("312", "311", "310"):
            if local:
                exe = Path(local) / "Programs" / "Python" / f"Python{v}" / "python.exe"
                if exe.exists():
                    cands.append([str(exe)])
        for c in cands:
            out = self._probe(c)
            if out in PY_OK:
                return c
        return None

    def _probe(self, cmd):
        try:
            r = subprocess.run(cmd + ["-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                               capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    def _winget_python(self, logf):
        self.step = "1/4 устанавливаю Python 3.12 (winget)…"
        self.log("GLaDOS: ставлю Python 3.12 через winget")
        rc = self._run(["winget", "install", "-e", "--id", "Python.Python.3.12", "--silent",
                        "--accept-package-agreements", "--accept-source-agreements"], self.base, logf)
        if rc != 0:
            self.log("GLaDOS: winget не смог поставить Python (код %s)" % rc)
        return self.find_python()

    # ---- запуск команд с записью в лог
    def _real_run(self, cmd, cwd, logf):
        with open(logf, "ab") as f:
            f.write(f"\n$ {' '.join(cmd)}\n".encode("utf-8", "replace"))
            f.flush()
            try:
                p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=NO_WINDOW)
            except FileNotFoundError:
                f.write(b"(command not found)\n")
                return 127
            for raw in p.stdout:
                f.write(raw)
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith(("Collecting ", "Successfully installed", "ERROR")):
                    self.log("GLaDOS: " + line[:140])
            return p.wait()
