"""Вход в Twitch без ручного копирования токена. Два способа:

А) Напрямую у Twitch (основной) — Device Code Grant Flow, приложение «TwitchTTS» на dev.twitch.tv (тип Public,
   без секрета — Client ID можно раздавать):
  1. POST id.twitch.tv/oauth2/device  ->  device_code, user_code, verification_uri (код уже вписан в ссылку)
  2. Человек открывает ссылку и жмёт «Разрешить».
  3. POST id.twitch.tv/oauth2/token (grant_type=device_code) — опрос, пока не придёт токен.
  4. Обновление — POST /oauth2/token (grant_type=refresh_token); refresh-токен одноразовый, сохраняем новый.

Б) Через twitchtokengenerator.com (запасной). Схема (официальный API сайта):
  1. GET /api/create/<название приложения в base64>/<права через +>  ->  {"success":true,"id":"...","message":"<ссылка для входа>"}
  2. Человек открывает ссылку, входит в Twitch и жмёт «Authorize».
  3. GET /api/status/<id>  ->  когда готово: токен (access) и refresh-токен.
  4. GET /api/refresh/<refresh-токен>  ->  новый токен, когда старый перестал работать.
Токен после получения проверяется у самого Twitch (id.twitch.tv/oauth2/validate): оттуда берём логин и список прав.
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://twitchtokengenerator.com"
APP_NAME = "TwitchTTS"
CLIENT_ID = "1sno9my149e3zho8pqfdtujwew4ikd"   # публичный номер приложения на dev.twitch.tv (не секрет)
ID_BASE = "https://id.twitch.tv/oauth2"
# что нужно приложению: читать чат, писать в чат, менять цену/состояние награды
SCOPES = ["chat:read", "chat:edit", "channel:manage:redemptions"]
UA = {"User-Agent": "TwitchTTS/1.0 (+token wizard)", "Accept": "application/json"}


class AuthError(Exception):
    pass


def _get_json(url, headers=None, timeout=15):
    """GET -> (HTTP-код, dict). Тело ошибок 4xx/5xx тоже разбираем: сайт кладёт пояснение в JSON."""
    req = urllib.request.Request(url, headers=headers or UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except Exception as e:
        raise AuthError(f"Нет связи с сайтом: {e}")
    try:
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        data = {"message": raw.decode("utf-8", "replace")[:200]}
    return code, data if isinstance(data, dict) else {"data": data}


def _post_form(url, fields, timeout=15):
    """POST application/x-www-form-urlencoded -> (HTTP-код, dict)."""
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={**UA, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except Exception as e:
        raise AuthError(f"Нет связи с Twitch: {e}")
    try:
        d = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        d = {"message": raw.decode("utf-8", "replace")[:200]}
    return code, d if isinstance(d, dict) else {"data": d}


def _direct_tokens(d):
    if not d.get("access_token"):
        return None
    scopes = d.get("scope") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    return {"token": str(d["access_token"]), "refresh": str(d.get("refresh_token") or ""), "scopes": list(scopes)}


def device_start(scopes=None, client_id=CLIENT_ID):
    """Начинает вход напрямую у Twitch. -> {"device_code","user_code","verification_uri","interval","expires_in"}."""
    code, d = _post_form(f"{ID_BASE}/device", {"client_id": client_id, "scopes": " ".join(scopes or SCOPES)})
    if code != 200 or not d.get("device_code") or not str(d.get("verification_uri", "")).startswith("http"):
        raise AuthError(f"Twitch не выдал код для входа (HTTP {code}): {d.get('message') or d}")
    return d


def device_poll(device_code, scopes=None, client_id=CLIENT_ID):
    """Один опрос. -> ({"token",...} или None, состояние). Состояние: pending | slow_down; AuthError — всё, конец."""
    code, d = _post_form(f"{ID_BASE}/token", {
        "client_id": client_id, "scopes": " ".join(scopes or SCOPES), "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    tokens = _direct_tokens(d)
    if code == 200 and tokens:
        return tokens, "ok"
    msg = str(d.get("message") or d.get("error") or "").lower()
    if "pending" in msg:
        return None, "pending"
    if "slow_down" in msg:
        return None, "slow_down"
    if "denied" in msg:
        raise AuthError("Вход отклонён в браузере")
    if "expired" in msg or "invalid device code" in msg:
        raise AuthError("Код входа устарел. Нажми «Войти» ещё раз.")
    raise AuthError(f"Twitch ответил ошибкой (HTTP {code}): {d.get('message') or d}")


def run_device_flow(on_url, on_tick=None, cancelled=None, scopes=None, client_id=CLIENT_ID):
    """Весь вход напрямую у Twitch. on_url(ссылка, код) — один раз, cancelled() -> True прерывает ожидание."""
    d = device_start(scopes, client_id)
    on_url(str(d["verification_uri"]), str(d.get("user_code", "")))
    interval = max(1.0, float(d.get("interval", 5) or 5))
    deadline = time.time() + min(float(d.get("expires_in", 1800) or 1800), 1800)
    errors = 0
    while time.time() < deadline:
        if cancelled and cancelled():
            raise AuthError("Отменено")
        time.sleep(interval)
        try:
            tokens, st = device_poll(d["device_code"], scopes, client_id)
            errors = 0
        except AuthError as e:
            if "Нет связи" not in str(e):
                raise
            errors += 1
            if errors >= 5:
                raise
            tokens, st = None, str(e)
        if st == "slow_down":
            interval += 5
        if on_tick:
            on_tick(st)
        if tokens:
            return tokens
    raise AuthError("Время ожидания вышло. Нажми «Войти» ещё раз.")


def refresh_direct(refresh_token, client_id=CLIENT_ID):
    """Обновление токена, полученного напрямую у Twitch. -> {"token","refresh","scopes"} или AuthError."""
    code, d = _post_form(f"{ID_BASE}/token", {"client_id": client_id, "grant_type": "refresh_token",
                                              "refresh_token": refresh_token})
    tokens = _direct_tokens(d)
    if code != 200 or not tokens:
        raise AuthError(f"Не удалось обновить токен у Twitch (HTTP {code}): {d.get('message') or d}")
    return tokens


def _pick(d, *names):
    """Достаёт значение по одному из имён, в том числе из вложенного "data"."""
    for src in (d, d.get("data") if isinstance(d.get("data"), dict) else {}):
        for n in names:
            v = src.get(n)
            if v:
                return v
    return None


def parse_tokens(d):
    """Ответ status/refresh -> {"token","refresh","scopes"}; None, если токена в ответе ещё нет."""
    token = _pick(d, "token", "access_token")
    if not token:
        return None
    scopes = _pick(d, "scopes", "scope") or []
    if isinstance(scopes, str):
        scopes = scopes.replace("+", " ").split()
    return {"token": str(token), "refresh": str(_pick(d, "refresh", "refresh_token") or ""), "scopes": list(scopes)}


def create(app_name=APP_NAME, scopes=None):
    """Начинает вход. Возвращает (id_входа, ссылка_для_браузера)."""
    scopes = scopes or SCOPES
    title = base64.b64encode(app_name.encode("utf-8")).decode("ascii")
    url = f"{BASE}/api/create/{urllib.parse.quote(title, safe='')}/{'+'.join(scopes)}"
    code, d = _get_json(url)
    link, flow_id = d.get("message"), d.get("id")
    if not d.get("success") or not flow_id or not str(link).startswith("http"):
        raise AuthError(f"Сайт не выдал ссылку для входа (HTTP {code}): {d.get('message') or d}")
    return str(flow_id), str(link)


def status(flow_id):
    """Один опрос. -> ({"token",...} или None, текст_для_пользователя)."""
    code, d = _get_json(f"{BASE}/api/status/{urllib.parse.quote(str(flow_id), safe='')}")
    tokens = parse_tokens(d)
    if tokens:
        return tokens, "Токен получен"
    msg = str(d.get("message") or d.get("error") or "")
    return None, msg or "Жду, пока ты разрешишь доступ в браузере…"


def refresh(refresh_token):
    """Обновляет токен. -> {"token","refresh","scopes"} или AuthError."""
    code, d = _get_json(f"{BASE}/api/refresh/{urllib.parse.quote(str(refresh_token), safe='')}")
    tokens = parse_tokens(d)
    if not tokens:
        raise AuthError(f"Не удалось обновить токен (HTTP {code}): {d.get('message') or d.get('error') or d}")
    return tokens


def validate(token):
    """Проверка у Twitch. -> {"login","user_id","client_id","scopes","expires_in"}; AuthError, если токен не принят."""
    code, d = _get_json("https://id.twitch.tv/oauth2/validate", {**UA, "Authorization": "OAuth " + token})
    if code == 401:
        raise AuthError("Twitch не принял токен (401)")
    if code != 200 or not d.get("login"):
        raise AuthError(f"Не удалось проверить токен у Twitch (HTTP {code})")
    return d


def run_flow(on_url, on_tick=None, cancelled=None, timeout=600, interval=2.0, app_name=APP_NAME, scopes=None):
    """Весь вход: ссылка -> ожидание -> токены. on_url(ссылка) вызывается один раз (открыть браузер),
    on_tick(текст) — при каждом опросе, cancelled() -> True прерывает ожидание."""
    flow_id, link = create(app_name, scopes)
    on_url(link)
    deadline = time.time() + timeout
    errors = 0
    while time.time() < deadline:
        if cancelled and cancelled():
            raise AuthError("Отменено")
        try:
            tokens, msg = status(flow_id)
            errors = 0
        except AuthError as e:
            errors += 1
            if errors >= 5:             # подряд 5 сбоев сети — сдаёмся, а не ждём вечно
                raise
            tokens, msg = None, str(e)
        if on_tick:
            on_tick(msg)
        if tokens:
            return tokens
        time.sleep(interval)
    raise AuthError("Время ожидания вышло (10 минут). Нажми «Войти» ещё раз.")
