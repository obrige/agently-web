"""agently-web — Agently (QQ Mail Agent) protocol client.

Reverse-engineered from @tencent-qqmail/agently-cli v1.0.18 (Go binary).
Pure Python standard library, zero dependencies.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

API_BASE = "https://api.agent.qq.com"
AUTH_BASE = "https://auth.agent.qq.com"
WEB_BASE = "https://agent.qq.com"
CLI_VERSION = "1.0.18"

# Build our own opener that bypasses any system HTTP proxy — `urllib.request.urlopen`
# reads HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings and picks up
# a proxy that breaks loopback calls in some environments. We never want it here.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
URLOPEN = _OPENER.open

_FORM = "application/x-www-form-urlencoded"


# User-Agent MUST start with `agently-cli/<version>` — the Agently auth API
# rejects other UAs with `{"errmsg":"unsupported client"}`. Confirmed against
# `https://auth.agent.qq.com/oauth/device?func=1` on the real server.
#
# We send exactly the same shape the Go CLI does: `agently-cli/<ver> (<os/arch>;
# agent/<agent-slug>)`. If AGENTLY_WEB_FAKE_UA=0, we omit our `(agently-web)`
# suffix so server-side grouping treats us exactly like the CLI.
def _detect_os_arch() -> tuple[str, str]:
    import platform

    sys = platform.system().lower()
    machine = platform.machine().lower()
    # Go-style canonical names
    os_map = {"darwin": "darwin", "linux": "linux", "windows": "win32"}
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    return os_map.get(sys, sys), arch_map.get(machine, machine)


_OS, _ARCH = _detect_os_arch()
_AGENT_SLUG = os.environ.get("AGENTLY_WEB_AGENT", "agently-web")


def _build_user_agent() -> str:
    base = f"agently-cli/{CLI_VERSION} ({_OS}/{_ARCH}"
    if _AGENT_SLUG:
        base += f"; agent/{_AGENT_SLUG}"
    if os.environ.get("AGENTLY_WEB_FAKE_UA") != "0":
        # Default: add a tiny suffix so server operators can spot non-CLI
        # requests. Disable by exporting AGENTLY_WEB_FAKE_UA=0 to mirror the
        # real CLI exactly.
        base += "; client/agently-web"
    return base + ")"


# Default header surface, matching Go's net/http defaults + the Agently UA
# requirement:
#
#   User-Agent:        agently-cli/<ver> (<os>/<arch>[; agent/<slug>])
#   Accept:            */*                  (Go's default)
#   Accept-Encoding:   gzip                 (Go's default; responses may be gzipped)
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": _build_user_agent(),
    "Accept": "*/*",
    "Accept-Encoding": "gzip",
}


# --------------------------------------------------------------------------- #
# HTTP plumbing
# --------------------------------------------------------------------------- #
def _decompress(body: bytes, content_encoding: str) -> bytes:
    """Decode a gzipped / deflated response body if the server asked us to."""
    if not body or not content_encoding:
        return body
    enc = content_encoding.lower()
    if "gzip" not in enc:
        return body
    import gzip

    try:
        return gzip.decompress(body)
    except OSError:
        return body


def _request(
    base: str | None,
    method: str,
    path: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, str], bytes]:
    """Perform a request and always return (status, headers, body).

    HTTP error statuses are *not* raised — the protocol uses 401/412 semantically
    and the caller needs the body either way.
    """
    url = path if base is None else base.rstrip("/") + "/" + path.lstrip("/")
    hdrs = dict(_DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with URLOPEN(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = resp.headers.get("Content-Encoding", "")
            return resp.status, dict(resp.headers), _decompress(raw, enc)
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a useful body
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        hdrs = dict(exc.headers or {})
        enc = hdrs.get("Content-Encoding", "")
        return exc.code, hdrs, _decompress(raw, enc)
    except urllib.error.URLError as exc:
        raise ConnectionError(f"{method} {url} failed: {exc.reason}") from exc


def _json(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _form(obj: dict[str, Any]) -> bytes:
    return urllib.parse.urlencode({k: v for k, v in obj.items() if v is not None}).encode("utf-8")


# Public alias for tests / external code.
formEncode = _form


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    """Error raised for a non-ok REST envelope or an HTTP failure."""

    def __init__(self, status: int, payload: Any):
        err = (payload or {}).get("error") or {}
        super().__init__(err.get("message") or f"HTTP {status}")
        self.status = status
        self.code = err.get("code") or ""
        self.request_id = err.get("request_id") or ""
        self.hints = err.get("_hints")
        self.payload = payload


# --------------------------------------------------------------------------- #
# OAuth 2.0 Device Authorization Grant (Agently flavour)
# --------------------------------------------------------------------------- #
class DeviceAuthorization:
    """Result of step 1 of the device flow."""

    __slots__ = (
        "scan_url",
        "poll_url",
        "browser_url",
        "input_code",
        "expires_in",
        "device_code",
        "user_code",
    )

    def __init__(self, **kw: Any):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


class Auth:
    """OAuth endpoints. Note: /oauth/device needs NO app credentials at all."""

    @staticmethod
    def request_device_authorization() -> DeviceAuthorization:
        # An empty form body is sufficient — app_id/app_secret are not required.
        status, _, body = _request(
            AUTH_BASE, "POST", "/oauth/device?func=1", data=b"", headers={"Content-Type": _FORM}
        )
        data = _json(body)
        if not isinstance(data, dict) or not data.get("poll_url") or not data.get("input_code"):
            raise ApiError(
                status,
                data or {"error": {"message": f"device authorization failed: {body[:200]!r}"}},
            )

        poll_qs = urllib.parse.parse_qs(urllib.parse.urlparse(data["poll_url"]).query)
        browser_qs = urllib.parse.parse_qs(urllib.parse.urlparse(data.get("browser_url", "")).query)
        return DeviceAuthorization(
            scan_url=data.get("scan_url", ""),
            poll_url=data["poll_url"],
            browser_url=data.get("browser_url", ""),
            input_code=data["input_code"],
            expires_in=int(data.get("expires_in") or 600),
            device_code=(poll_qs.get("device_code") or [""])[0],
            user_code=(browser_qs.get("user_code") or [""])[0],
        )

    @staticmethod
    def poll_status(poll_url: str) -> dict[str, Any]:
        """Step 2 — poll for authorization. Must use form encoding, not JSON."""
        status, _, body = _request(
            None, "POST", poll_url, data=b"", headers={"Content-Type": _FORM}
        )
        return {"status": status, "body": _json(body) or {}}

    @staticmethod
    def exchange_token(input_code: str) -> dict[str, Any]:
        """Step 3 — trade the input_code for tokens.

        Returns {"pending": True} with HTTP 412 when the user has not finished
        authorizing yet — that is the signal to keep waiting.
        """
        status, _, body = _request(
            AUTH_BASE,
            "POST",
            "/oauth/token",
            data=_form({"input_code": input_code}),
            headers={"Content-Type": _FORM},
        )
        if status == 412:
            return {"pending": True, "status": status}
        data = _json(body)
        if not isinstance(data, dict) or not data.get("access_token"):
            desc = (data or {}).get("error_description") or (data or {}).get("error")
            raise ApiError(
                status,
                data or {"error": {"message": desc or f"token exchange failed (HTTP {status})"}},
            )
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_in": int(data.get("expires_in") or 0),
            "expires_at": int(data.get("expires_at") or 0),
        }

    @staticmethod
    def refresh_token(refresh_token: str) -> dict[str, Any]:
        status, _, body = _request(
            AUTH_BASE,
            "POST",
            "/oauth/token",
            data=_form({"grant_type": "refresh_token", "refresh_token": refresh_token}),
            headers={"Content-Type": _FORM},
        )
        data = _json(body)
        if not isinstance(data, dict) or not data.get("access_token"):
            desc = (data or {}).get("error_description") or (data or {}).get("error")
            raise ApiError(
                status, data or {"error": {"message": desc or f"refresh failed (HTTP {status})"}}
            )
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or refresh_token,
            "expires_in": int(data.get("expires_in") or 0),
            "expires_at": int(data.get("expires_at") or 0),
        }

    @staticmethod
    def logout(refresh_token: str) -> dict[str, Any]:
        status, _, body = _request(
            AUTH_BASE,
            "POST",
            "/oauth/logout_session",
            data=_form({"refresh_token": refresh_token}),
            headers={"Content-Type": _FORM},
        )
        return {"status": status, "body": _json(body)}


# --------------------------------------------------------------------------- #
# REST API — https://api.agent.qq.com/v1
# --------------------------------------------------------------------------- #
class AgentlyApi:
    """Mail API. Envelope: {"ok": true, "data": ...} | {"ok": false, "error": {...}}."""

    def __init__(self, token_getter: Callable[[], str | None]):
        self._token_getter = token_getter

    # -- core -------------------------------------------------------------- #
    def call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: dict[str, Any] | None = None,
        raw: bytes | None = None,
        content_type: str | None = None,
        timeout: int = 30,
    ) -> Any:
        token = self._token_getter()
        if not token:
            raise ApiError(
                401, {"error": {"code": "AUTHENTICATION_REQUIRED", "message": "not authenticated"}}
            )

        full = path
        if query:
            qs = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
            if qs:
                full += ("&" if "?" in full else "?") + qs

        headers = {"Authorization": f"Bearer {token}"}
        payload: bytes | None = None
        if raw is not None:
            payload = raw
            if content_type:
                headers["Content-Type"] = content_type
        elif body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        status, _, resp_body = _request(
            API_BASE, method, full, data=payload, headers=headers, timeout=timeout
        )
        data = _json(resp_body)

        if status == 401:
            raise ApiError(
                401,
                data or {"error": {"code": "AUTHENTICATION_REQUIRED", "message": "unauthorized"}},
            )
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ApiError(status, data if isinstance(data, dict) else {})
        return data.get("data")

    # -- identity ---------------------------------------------------------- #
    def me(self) -> Any:
        return self.call("GET", "/v1/me")

    def aliases(self) -> Any:
        return self.call("GET", "/v1/aliases")

    # -- messages ---------------------------------------------------------- #
    def list_messages(
        self,
        alias_id: str,
        *,
        limit: int = 25,
        before: str | None = None,
        is_read: bool | None = None,
        folder: str | None = None,
    ) -> Any:
        query: dict[str, Any] = {"limit": limit}
        if before:
            query["before"] = before
        if is_read is not None:
            query["is-read"] = "true" if is_read else "false"
        if folder:
            query["folder"] = folder
        return self.call("GET", f"/v1/aliases/{_esc(alias_id)}/messages", query=query)

    def get_message(self, alias_id: str, message_id: str) -> Any:
        return self.call("GET", f"/v1/aliases/{_esc(alias_id)}/messages/{_esc(message_id)}")

    def search_messages(self, alias_id: str, q: str, *, scope: str | None = None) -> Any:
        query: dict[str, Any] = {"q": q}
        if scope:
            query["search-in"] = scope
        return self.call("GET", f"/v1/aliases/{_esc(alias_id)}/messages/search", query=query)

    def send_message(self, alias_id: str, payload: dict[str, Any]) -> Any:
        return self.call("POST", f"/v1/aliases/{_esc(alias_id)}/messages/sendapi", body=payload)

    def reply_message(self, alias_id: str, message_id: str, payload: dict[str, Any]) -> Any:
        return self.call(
            "POST", f"/v1/aliases/{_esc(alias_id)}/messages/{_esc(message_id)}/reply", body=payload
        )

    def forward_message(self, alias_id: str, message_id: str, payload: dict[str, Any]) -> Any:
        return self.call(
            "POST",
            f"/v1/aliases/{_esc(alias_id)}/messages/{_esc(message_id)}/forward",
            body=payload,
        )

    def trash_message(self, alias_id: str, message_id: str) -> Any:
        """Soft delete — move to trash."""
        return self.call("DELETE", f"/v1/aliases/{_esc(alias_id)}/messages/{_esc(message_id)}")

    def delete_message(self, alias_id: str, message_id: str) -> Any:
        """Hard delete — releases mailbox storage."""
        return self.call(
            "POST", f"/v1/aliases/{_esc(alias_id)}/messages/{_esc(message_id)}/permanent", body={}
        )

    def empty_trash(self, alias_id: str) -> Any:
        return self.call(
            "POST", f"/v1/aliases/{_esc(alias_id)}/dir/trash/messages/permanent", body={}
        )

    # -- attachments ------------------------------------------------------- #
    def upload_file(self, alias_id: str, data: bytes, filename: str, content_type: str) -> Any:
        boundary = "----agentlyweb" + urllib.parse.quote_plus(str(id(data)))
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename.replace(chr(34), "")}"\r\n'
            f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        raw = head + data + tail
        return self.call(
            "POST",
            f"/v1/aliases/{_esc(alias_id)}/files/upload",
            raw=raw,
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def download_attachment(self, alias_id: str, message_id: str, attachment_id: str) -> Any:
        return self.call(
            "GET",
            f"/v1/aliases/{_esc(alias_id)}/messages/{_esc(message_id)}/attachments/{_esc(attachment_id)}",
        )

    # -- events ------------------------------------------------------------ #
    def watch_events(self, alias_id: str, *, timeout: int = 60) -> Any:
        return self.call("GET", f"/v1/aliases/{_esc(alias_id)}/events/wait", timeout=timeout + 5)


def _esc(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")
