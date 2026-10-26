#!/usr/bin/env python3
"""agently-web — Gmail-style web client for the Agently (QQ Mail Agent) protocol.

Pure Python standard library. No pip install required.

    python server.py                     →  http://127.0.0.1:8787
    AGENTLY_WEB_DEMO=1 python server.py  →  demo mode, no QQ account needed
    PORT=3000 python server.py           →  custom port
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from agently.client import API_BASE, WEB_BASE, AgentlyApi, ApiError, Auth  # noqa: E402
from agently.normalize import normalise_me  # noqa: E402
from agently.store import AccountStore  # noqa: E402

PORT = int(os.environ.get("PORT", 8787))
HOST = os.environ.get("HOST", "0.0.0.0")
DEMO = os.environ.get("AGENTLY_WEB_DEMO") == "1"
STATIC_DIR = BASE_DIR / "static"
MAX_BODY = 32 * 1024 * 1024

if DEMO:
    from agently.demo import DemoStore, _ensure_singleton

    store = DemoStore()
    _demo_api = _ensure_singleton()
else:
    store = AccountStore()

# One lock guards every store mutation and the demo mailbox — the server is
# threaded (long-polling /events/wait would otherwise serialise everything).
LOCK = threading.RLock()

SESSION_COOKIE = "agently_web_sid"
SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000

SESSIONS: dict[str, dict[str, Any]] = {}
LOGINS: dict[str, dict[str, Any]] = {}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def parse_cookies(header: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not header:
        return out
    for part in header.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = unquote(v.strip())
    return out


def get_session(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
    sid = parse_cookies(handler.headers.get("Cookie")).get(SESSION_COOKIE)
    if not sid:
        return None
    s = SESSIONS.get(sid)
    if not s:
        return None
    if time.time() * 1000 - s["createdAt"] > SESSION_TTL_MS:
        SESSIONS.pop(sid, None)
        return None
    return {"sid": sid, **s}


def create_session(account_id: str) -> str:
    sid = secrets.token_hex(24)
    SESSIONS[sid] = {"accountId": account_id, "createdAt": int(time.time() * 1000)}
    return sid


# --------------------------------------------------------------------------- #
# Token accessor with automatic refresh
# --------------------------------------------------------------------------- #
def get_access_token(account_id: str) -> str:
    with LOCK:
        acc = store.get(account_id)
    if not acc:
        raise ApiError(
            401, {"error": {"code": "AUTHENTICATION_REQUIRED", "message": "account not found"}}
        )
    token = acc.get("accessToken")
    if not token:
        raise ApiError(
            401, {"error": {"code": "AUTHENTICATION_REQUIRED", "message": "not authenticated"}}
        )

    now = int(time.time())
    expires_at = int(acc.get("expiresAt") or 0)
    if expires_at and expires_at - now < 60 and acc.get("refreshToken"):
        try:
            fresh = Auth.refresh_token(acc["refreshToken"])
            with LOCK:
                store.update_tokens(account_id, fresh)
            return fresh["access_token"]
        except Exception:
            pass  # fall through — the server will tell us if it is really dead
    return token


def api_for(account_id: str) -> Any:
    if DEMO:
        return _demo_api
    return AgentlyApi(lambda: get_access_token(account_id))


# --------------------------------------------------------------------------- #
# Device-flow login orchestration
# --------------------------------------------------------------------------- #
def start_login() -> dict[str, Any]:
    if DEMO:
        with LOCK:
            account_id = store.create_pending()
        login_id = secrets.token_hex(6)
        entry = {
            "loginId": login_id,
            "accountId": account_id,
            "pollUrl": "",
            "inputCode": "",
            "browserUrl": "about:blank#demo",
            "userCode": "DEMO-0000",
            "expiresIn": 600,
            "deadline": time.time() * 1000 + 600_000,
            "status": "pending",
            "error": "",
        }
        LOGINS[login_id] = entry
        threading.Timer(1.5, poll_login, args=(login_id,)).start()
        return entry

    dev = Auth.request_device_authorization()
    with LOCK:
        account_id = store.create_pending()
    login_id = secrets.token_hex(6)
    entry = {
        "loginId": login_id,
        "accountId": account_id,
        "pollUrl": dev.poll_url,
        "inputCode": dev.input_code,
        "browserUrl": dev.browser_url,
        "userCode": dev.user_code,
        "expiresIn": dev.expires_in,
        "deadline": time.time() * 1000 + dev.expires_in * 1000,
        "status": "pending",
        "error": "",
    }
    LOGINS[login_id] = entry
    threading.Thread(target=_poll_loop, args=(login_id,), daemon=True).start()
    return entry


def _poll_loop(login_id: str) -> None:
    while True:
        entry = LOGINS.get(login_id)
        if not entry or entry["status"] != "pending":
            return
        with contextlib.suppress(Exception):
            poll_login(login_id)
        entry = LOGINS.get(login_id)
        if not entry or entry["status"] != "pending":
            return
        time.sleep(2)


def poll_login(login_id: str) -> dict[str, Any] | None:
    entry = LOGINS.get(login_id)
    if not entry or entry["status"] != "pending":
        return entry

    status = ""
    if DEMO:
        status = "authorized"
    else:
        try:
            poll = Auth.poll_status(entry["pollUrl"])
        except Exception:
            return entry
        body = poll["body"] or {}
        status = str(body.get("status") or "")
        if body.get("authorized") is True:
            status = "authorized"

    if status in ("authorized", "verified"):
        if DEMO:
            tokens = {
                "accessToken": "demo-token",
                "refreshToken": "demo-refresh",
                "expiresIn": 3600,
                "expiresAt": int(time.time()) + 3600,
            }
        else:
            try:
                raw = Auth.exchange_token(entry["inputCode"])
                if raw.get("pending"):
                    return entry
                tokens = {
                    "accessToken": raw["access_token"],
                    "refreshToken": raw["refresh_token"],
                    "expiresIn": raw["expires_in"],
                    "expiresAt": raw["expires_at"],
                }
            except Exception as exc:
                entry["status"] = "error"
                entry["error"] = str(exc)
                with LOCK:
                    store.fail_login(entry["accountId"], entry["error"])
                return entry

        with LOCK:
            store.complete_login(entry["accountId"], tokens)
        entry["status"] = "complete"
        try:
            me = api_for(entry["accountId"]).me()
            with LOCK:
                store.set_profile(entry["accountId"], normalise_me(me))
        except Exception:
            pass
    elif status in ("denied", "access_denied", "expired", "expired_token"):
        entry["status"] = "error"
        entry["error"] = f"Authorization {status}."
        with LOCK:
            store.fail_login(entry["accountId"], entry["error"])
    return entry


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agently-web/1.0"

    # -- silence the default stderr access log ---------------------------- #
    def log_message(self, *args: Any) -> None:  # noqa: D102
        pass

    # -- helpers ---------------------------------------------------------- #
    def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        hdrs = {"Content-Length": str(len(body))}
        if headers:
            hdrs.update(headers)
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: Any, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(
            status, body, {"Content-Type": "application/json; charset=utf-8", **(headers or {})}
        )

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > MAX_BODY:
            raise ApiError(
                413, {"error": {"code": "PAYLOAD_TOO_LARGE", "message": "payload too large"}}
            )
        return self.rfile.read(length)

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    def _cookie_header(self, sid: str) -> str:
        return f"{SESSION_COOKIE}={sid}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_MS // 1000}"

    # -- CORS ------------------------------------------------------------- #
    def _cors(self) -> None:
        origin = self.headers.get("Origin") or "*"
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- entry points ----------------------------------------------------- #
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    # -- router ----------------------------------------------------------- #
    def _dispatch(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            qs = parse_qs(parsed.query)

            if not path.startswith("/api/"):
                if path == "/healthz":
                    return self._json(200, {"ok": True, "service": "agently-web"})
                return self._static(path)

            route = path[len("/api/") :]
            handler = getattr(self, f"_r_{method.lower()}", None)
            if handler is None:
                return self._json(
                    405,
                    {
                        "ok": False,
                        "error": {"code": "METHOD_NOT_ALLOWED", "message": f"{method} not allowed"},
                    },
                )
            return handler(route, qs)
        except ApiError as exc:
            self._json(
                exc.status,
                {
                    "ok": False,
                    "error": {
                        "code": exc.code or "ERROR",
                        "message": str(exc),
                        **({"request_id": exc.request_id} if exc.request_id else {}),
                        **({"_hints": exc.hints} if exc.hints else {}),
                    },
                },
            )
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            if os.environ.get("AGENTLY_WEB_DEBUG"):
                traceback.print_exc()
            self._json(500, {"ok": False, "error": {"code": "INTERNAL", "message": str(exc)}})

    # -- static ----------------------------------------------------------- #
    def _static(self, path: str) -> None:
        rel = "/index.html" if path == "/" else path
        target = (STATIC_DIR / rel.lstrip("/")).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return self._send(403, b"forbidden", {"Content-Type": "text/plain"})
        if not target.is_file():
            return self._send(404, b"not found", {"Content-Type": "text/plain"})
        data = target.read_bytes()
        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, data, {"Content-Type": ctype, "Cache-Control": "no-cache"})

    # =================================================================== #
    # GET routes
    # =================================================================== #
    def _r_get(self, route: str, qs: dict[str, list[str]]) -> None:
        q = lambda k, d=None: (qs.get(k) or [d])[0]  # noqa: E731

        # ---- auth: session bootstrap (no session required) ---- #
        if route == "auth/session":
            s = get_session(self)
            accounts = store.list()
            if not s:
                return self._json(
                    200, {"ok": True, "data": {"loggedIn": False, "accounts": accounts}}
                )
            acc = store.get(s["accountId"])
            if not acc:
                SESSIONS.pop(s["sid"], None)
                return self._json(
                    200, {"ok": True, "data": {"loggedIn": False, "accounts": accounts}}
                )
            return self._json(
                200,
                {
                    "ok": True,
                    "data": {
                        "loggedIn": True,
                        "accountId": s["accountId"],
                        "email": acc.get("email", ""),
                        "aliasId": acc.get("aliasId", ""),
                        "displayName": acc.get("displayName") or acc.get("email", ""),
                        "profile": acc.get("profile"),
                        "accounts": accounts,
                    },
                },
            )

        if re.fullmatch(r"auth/login/([\w-]+)", route):
            return self._login_poll(re.fullmatch(r"auth/login/([\w-]+)", route).group(1))

        # ---- everything below needs a session ---- #
        session = get_session(self)
        if not session:
            return self._json(
                401,
                {
                    "ok": False,
                    "error": {"code": "AUTHENTICATION_REQUIRED", "message": "Please sign in."},
                },
            )
        account_id = session["accountId"]
        api = api_for(account_id)

        if route == "me":
            me = api.me()
            norm = normalise_me(me)
            with LOCK:
                store.set_profile(account_id, norm)
            return self._json(
                200,
                {
                    "ok": True,
                    "data": {**norm, "raw": me, "accountId": account_id, "accounts": store.list()},
                },
            )

        if route == "aliases":
            with LOCK:
                prof = (store.get(account_id) or {}).get("profile")
            if not prof:
                prof = normalise_me(api.me())
                with LOCK:
                    store.set_profile(account_id, prof)
            return self._json(
                200,
                {
                    "ok": True,
                    "data": {"aliases": prof["aliases"], "defaultAliasId": prof["aliasId"]},
                },
            )

        if route == "accounts":
            return self._json(200, {"ok": True, "data": store.list()})

        # ---- drafts (autosave) ---- #
        if route == "drafts":
            return self._json(200, {"ok": True, "data": store.list_drafts(account_id)})

        m = re.fullmatch(r"drafts/([\w\-]+)", route)
        if m:
            d = store.get_draft(account_id, m.group(1))
            if not d:
                return self._json(404, {"ok": False, "error": {"message": "draft not found"}})
            return self._json(200, {"ok": True, "data": d})

        # ---- signature ---- #
        if route == "signature":
            return self._json(200, {"ok": True, "data": store.get_signature(account_id)})

        # ---- stars ---- #
        if route == "stars":
            return self._json(200, {"ok": True, "data": store.list_stars(account_id)})

        # ---- contacts ---- #
        if route == "contacts":
            return self._json(200, {"ok": True, "data": store.list_contacts(account_id)})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages", route)
        if m:
            return self._list_messages(api, m.group(1), qs)

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/search", route)
        if m:
            data = api.search_messages(m.group(1), q("q", ""), scope=q("search-in"))
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/([\w\-.]+)/attachments/([\w\-.]+)", route)
        if m:
            data = api.download_attachment(m.group(1), m.group(2), m.group(3))
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/([\w\-.]+)", route)
        if m:
            data = api.get_message(m.group(1), m.group(2))
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/events/wait", route)
        if m:
            data = api.watch_events(m.group(1), timeout=55)
            return self._json(200, {"ok": True, "data": data})

        self._json(
            404,
            {
                "ok": False,
                "error": {"code": "NOT_FOUND", "message": f"no route for GET /api/{route}"},
            },
        )

    # =================================================================== #
    # POST routes
    # =================================================================== #
    def _r_post(self, route: str, qs: dict[str, list[str]]) -> None:
        q = lambda k, d=None: (qs.get(k) or [d])[0]  # noqa: E731

        if route == "auth/login/start":
            entry = start_login()
            return self._json(
                200,
                {
                    "ok": True,
                    "data": {
                        "loginId": entry["loginId"],
                        "browserUrl": entry["browserUrl"],
                        "userCode": entry["userCode"],
                        "expiresIn": entry["expiresIn"],
                        "status": entry["status"],
                    },
                },
            )

        m = re.fullmatch(r"auth/login/([\w-]+)/cancel", route)
        if m:
            entry = LOGINS.pop(m.group(1), None)
            if entry:
                with LOCK:
                    store.remove(entry["accountId"])
            return self._json(200, {"ok": True, "data": {"cancelled": True}})

        if route == "auth/switch":
            body = self._read_json()
            acc = store.get(body.get("accountId", ""))
            if not acc:
                return self._json(404, {"ok": False, "error": {"message": "account not found"}})
            return self._json(
                200,
                {"ok": True, "data": {"accountId": body["accountId"]}},
                {"Set-Cookie": self._cookie_header(create_session(body["accountId"]))},
            )

        if route == "auth/logout":
            s = get_session(self)
            if s:
                acc = store.get(s["accountId"]) or {}
                if acc.get("refreshToken"):
                    with contextlib.suppress(Exception):
                        Auth.logout(acc["refreshToken"])
                with LOCK:
                    store.remove(s["accountId"])
                SESSIONS.pop(s["sid"], None)
            return self._json(
                200,
                {"ok": True, "data": {"loggedOut": True}},
                {"Set-Cookie": f"{SESSION_COOKIE}=; Path=/; HttpOnly; Max-Age=0"},
            )

        session = get_session(self)
        if not session:
            return self._json(
                401,
                {
                    "ok": False,
                    "error": {"code": "AUTHENTICATION_REQUIRED", "message": "Please sign in."},
                },
            )
        account_id = session["accountId"]
        api = api_for(account_id)

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/send", route)
        if m:
            data = api.send_message(m.group(1), self._read_json())
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/([\w\-.]+)/reply", route)
        if m:
            data = api.reply_message(m.group(1), m.group(2), self._read_json())
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/([\w\-.]+)/forward", route)
        if m:
            data = api.forward_message(m.group(1), m.group(2), self._read_json())
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/([\w\-.]+)/permanent", route)
        if m:
            data = api.delete_message(m.group(1), m.group(2))
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/trash/empty", route)
        if m:
            data = api.empty_trash(m.group(1))
            return self._json(200, {"ok": True, "data": data})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/files/upload", route)
        if m:
            raw = self._read_body()
            data = api.upload_file(
                m.group(1),
                raw,
                q("filename", "attachment"),
                q("content-type", "application/octet-stream"),
            )
            return self._json(200, {"ok": True, "data": data})

        # ---- drafts (autosave) ---- #
        if route == "drafts":
            body = self._read_json()
            draft = store.upsert_draft(account_id, body)
            return self._json(200, {"ok": True, "data": draft})

        # ---- signature ---- #
        if route == "signature":
            sig = store.set_signature(account_id, self._read_json())
            return self._json(200, {"ok": True, "data": sig})

        # ---- stars: POST /api/stars/{mid} ---- #
        m = re.fullmatch(r"stars/([\w\-.]+)", route)
        if m:
            added = store.star(account_id, m.group(1))
            return self._json(
                200,
                {"ok": True, "data": {"messageId": m.group(1), "starred": True, "changed": added}},
            )

        # ---- contacts ---- #
        if route == "contacts":
            body = self._read_json()
            email = (body.get("email") or "").strip()
            if not email:
                return self._json(400, {"ok": False, "error": {"message": "email required"}})
            contact = store.add_contact(account_id, email, body.get("name", ""))
            return self._json(200, {"ok": True, "data": contact})

        self._json(
            404,
            {
                "ok": False,
                "error": {"code": "NOT_FOUND", "message": f"no route for POST /api/{route}"},
            },
        )

    # =================================================================== #
    # DELETE routes
    # =================================================================== #
    def _r_delete(self, route: str, qs: dict[str, list[str]]) -> None:
        session = get_session(self)
        if not session:
            return self._json(
                401,
                {
                    "ok": False,
                    "error": {"code": "AUTHENTICATION_REQUIRED", "message": "Please sign in."},
                },
            )
        account_id = session["accountId"]
        api = api_for(account_id)

        m = re.fullmatch(r"accounts/([\w-]+)", route)
        if m:
            target = store.get(m.group(1)) or {}
            if target.get("refreshToken"):
                with contextlib.suppress(Exception):
                    Auth.logout(target["refreshToken"])
            with LOCK:
                store.remove(m.group(1))
            return self._json(200, {"ok": True, "data": {"removed": m.group(1)}})

        m = re.fullmatch(r"aliases/([\w\-.@]+)/messages/([\w\-.]+)", route)
        if m:
            data = api.trash_message(m.group(1), m.group(2))
            return self._json(200, {"ok": True, "data": data})

        # ---- drafts ---- #
        m = re.fullmatch(r"drafts/([\w\-]+)", route)
        if m:
            ok = store.delete_draft(account_id, m.group(1))
            return self._json(200, {"ok": True, "data": {"removed": ok}})

        # ---- stars ---- #
        m = re.fullmatch(r"stars/([\w\-.]+)", route)
        if m:
            ok = store.unstar(account_id, m.group(1))
            return self._json(
                200,
                {"ok": True, "data": {"messageId": m.group(1), "starred": False, "changed": ok}},
            )

        # ---- contacts ---- #
        m = re.fullmatch(r"contacts/(.+)", route)
        if m:
            email = unquote(m.group(1))
            ok = store.remove_contact(account_id, email)
            return self._json(200, {"ok": True, "data": {"removed": ok}})

        self._json(
            404,
            {
                "ok": False,
                "error": {"code": "NOT_FOUND", "message": f"no route for DELETE /api/{route}"},
            },
        )

    # =================================================================== #
    # shared route bodies
    # =================================================================== #
    def _login_poll(self, login_id: str) -> None:
        entry = poll_login(login_id)
        if not entry:
            return self._json(404, {"ok": False, "error": {"message": "unknown login"}})
        if entry["status"] == "complete":
            return self._json(
                200,
                {"ok": True, "data": {"status": "complete", "accountId": entry["accountId"]}},
                {"Set-Cookie": self._cookie_header(create_session(entry["accountId"]))},
            )
        left = max(0, int((entry["deadline"] - time.time() * 1000) / 1000))
        return self._json(
            200,
            {
                "ok": True,
                "data": {
                    "status": entry["status"],
                    "error": entry["error"] or None,
                    "expiresIn": left,
                },
            },
        )

    def _list_messages(self, api: Any, alias_id: str, qs: dict[str, list[str]]) -> None:
        def q(k: str, d: Any = None) -> Any:
            return (qs.get(k) or [d])[0]

        try:
            limit = min(int(q("limit", 25)), 50)
        except (TypeError, ValueError):
            limit = 25
        before = q("before")
        is_read_raw = q("is-read")
        is_read = None if is_read_raw is None else (is_read_raw != "false")
        data = api.list_messages(
            alias_id, limit=limit, before=before, is_read=is_read, folder=q("folder")
        )
        self._json(200, {"ok": True, "data": data})


# --------------------------------------------------------------------------- #
# Server bootstrap
# --------------------------------------------------------------------------- #
class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _local_ip() -> str:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    if not STATIC_DIR.is_dir():
        print(f"[warn] static dir not found: {STATIC_DIR}", file=sys.stderr)

    mode = "DEMO (no credentials needed)" if DEMO else "LIVE (OAuth login required)"
    print()
    print("  " + "=" * 58)
    print("   agently-web - Agently (QQ Mail) web client")
    print(f"   mode: {mode}")
    print("  " + "=" * 58)
    print()
    print(f"   Local : http://127.0.0.1:{PORT}")
    print(f"   LAN   : http://{_local_ip()}:{PORT}")
    print(f"   Auth  : {WEB_BASE}/page/oauth")
    print(f"   API   : {API_BASE}/v1")
    print()
    print("   Press Ctrl+C to stop.")
    print()

    try:
        Server((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n   stopped.")


if __name__ == "__main__":
    main()
