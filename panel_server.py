"""Локальный веб-сервер панели управления (для «Пользовательской док-панели браузера» OBS).

Слушает только 127.0.0.1; доступ по секретному ключу из config.json (параметр ?k=...).
"""
import hashlib
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from panel_html import PANEL_HTML


def start_panel(bot, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _allowed(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("127.0.0.1", "localhost"):  # защита от DNS rebinding
                return False
            q = parse_qs(urlparse(self.path).query)
            key = (q.get("k") or [self.headers.get("X-Key", "")])[0]
            return secrets.compare_digest(key.encode(), bot.cfg["panel_key"].encode())

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False)
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._allowed():
                return self._send(403, "forbidden", "text/plain")
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, PANEL_HTML, "text/html; charset=utf-8")
            elif path == "/api/state":
                # панель присылает версию того, что уже показывает: если ничего не поменялось — 204 без тела
                body = json.dumps(bot.snapshot(), ensure_ascii=False)
                ver = hashlib.blake2s(body.encode("utf-8"), digest_size=8).hexdigest()
                if (parse_qs(urlparse(self.path).query).get("v") or [""])[0] == ver:
                    self.send_response(204)
                    self.send_header("X-V", ver)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                self._send(200, body, extra={"X-V": ver})
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            if not self._allowed():
                return self._send(403, "forbidden", "text/plain")
            if urlparse(self.path).path != "/api/action":
                return self._send(404, "not found", "text/plain")
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 4000000)   # до ~3 МБ — загрузка звука
                data = json.loads(self.rfile.read(n) or b"{}")
                msg = bot.do_action(data)
                self._send(200, {"ok": True, "msg": msg or ""})
            except Exception as e:
                self._send(400, {"ok": False, "msg": str(e)})

    last_err = None
    for p in range(int(port), int(port) + 15):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever, daemon=True).start()
            return server, p
        except OSError as e:
            last_err = e
    raise OSError(f"Не удалось занять порт для панели: {last_err}")
