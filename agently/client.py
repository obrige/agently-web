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
import uuid
from collections.abc import Callable
from typing import Any, cast

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
_JSON = "application/json"


# User-Agent MUST start with `agently-cli/<version>` — the Agently auth API
# rejects other UAs with `{"errmsg":"unsupported client"}`. Confirmed against
# `https://auth.agent.qq.com/oauth/device?func=1` on the real server.
#
# The official CLI sends `agently-cli/<ver> (<os>/<arch>)` and only appends
# `; agent/<slug>` when it detects an agent harness around it.  We send the
# very same string — the captured wire format of the official client is
# `agently-cli/1.0.18 (windows/amd64)`.  Set AGENTLY_WEB_FAKE_UA=1 to add a
# `; client/agently-web` marker so server operators can spot non-CLI
# requests, and AGENTLY_WEB_AGENT=<slug> to announce an agent harness.
def _detect_os_arch() -> tuple[str, str]:
    import platform

    sys = platform.system().lower()
    machine = platform.machine().lower()
    # Go-style canonical names (runtime.GOOS / runtime.GOARCH)
    os_map = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    return os_map.get(sys, sys), arch_map.get(machine, machine)


_OS, _ARCH = _detect_os_arch()
_AGENT_SLUG = os.environ.get("AGENTLY_WEB_AGENT", "")


def _build_user_agent() -> str:
    base = f"agently-cli/{CLI_VERSION} ({_OS}/{_ARCH}"
    if _AGENT_SLUG:
        base += f"; agent/{_AGENT_SLUG}"
    if os.environ.get("AGENTLY_WEB_FAKE_UA") == "1":
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


def _dict(data: Any) -> dict[str, Any]:
    """Return ``data`` when it is a JSON object, an empty dict otherwise.

    The Agently API does not always answer with an object: an error reply can
    be a bare string or a list. Every caller that reaches into a decoded
    payload has to go through this guard instead of calling ``.get()`` blind —
    otherwise a plain string blows up with
    ``'str' object has no attribute 'get'``.
    """
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _form(obj: dict[str, Any]) -> bytes:
    return urllib.parse.urlencode({k: v for k, v in obj.items() if v is not None}).encode("utf-8")


# Public alias for tests / external code.
formEncode = _form


# --------------------------------------------------------------------------- #
# The device-flow protocol, as observed on the wire
# --------------------------------------------------------------------------- #
# Everything below was captured from the *official* client
# (@tencent-qqmail/agently-cli v1.0.18) by replaying its traffic through a
# MITM proxy, and then confirmed against the live server:
#
#   1) POST /oauth/device?func=1      Content-Type: application/json
#           {"cli_hostname": "<uuid>", "cli_ua": "<ua>", "cli_version": "1.0.18"}
#        -> {"scan_url", "poll_url", "browser_url", "input_code", "expires_in"}
#
#   2) GET  <poll_url>                long poll, no request body
#        -> {"status": "pending"} while the user has not approved the device
#        -> {"status": "authorized", ...} once they did
#
#   3) POST /oauth/token              Content-Type: application/x-www-form-urlencoded
#           grant_type=authorization_code&code=<code>&client_id=<id>
#        -> {"access_token", "refresh_token", "expires_in", "expires_at",
#            "app_id", "app_secret"}
#
# The token endpoint is strict: it answers HTTP 401
# {"err_code": -20011, "error": "invalid_request"} for every parameter set it
# does not understand, and only switches to a meaningful error
# ({"err_code": -21651, "error": "invalid_client"}) once the shape is right.
# That is how the shape above was pinned down — see AGENTLY_WEB_CLIENT_ID.

# The token endpoint insists on a client_id. The device flow hands one out
# together with the token; these env vars are the escape hatch for setups
# where it is provisioned out of band.
CLIENT_ID = os.environ.get("AGENTLY_WEB_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("AGENTLY_WEB_CLIENT_SECRET", "")

# The poll endpoint holds the connection open for ~20 s before it answers.
POLL_TIMEOUT = 65


def _is_unsupported_shape(payload: Any) -> bool:
    """True when the endpoint simply did not understand our parameters."""
    body = _dict(payload)
    if body.get("err_code") == -20011:
        return True
    desc = str(body.get("error_description") or body.get("errmsg") or "").lower()
    return "missing or malformed" in desc


def _token_from_payload(payload: Any) -> dict[str, Any] | None:
    """Pull a token bundle out of a payload, wherever it hides.

    The authorization response carries the token at the top level, but it may
    also be wrapped in ``token`` / ``data`` / ``device_token``; accept all of
    them instead of guessing a single layout.
    """
    body = _dict(payload)
    candidates: list[dict[str, Any]] = [body]
    for key in ("token", "tokens", "data", "device_token", "result"):
        nested = body.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    for cand in candidates:
        if cand.get("access_token"):
            return {
                "access_token": str(cand.get("access_token") or ""),
                "refresh_token": str(cand.get("refresh_token") or ""),
                "expires_in": int(cand.get("expires_in") or 0),
                "expires_at": int(cand.get("expires_at") or 0),
                "app_id": str(cand.get("app_id") or ""),
                "app_secret": str(cand.get("app_secret") or ""),
            }
    return None


def _client_credentials_from_payload(payload: Any) -> dict[str, str]:
    """Pick the client credentials out of an authorization payload.

    The authorization response names them ``app_id`` / ``app_secret``; the
    token endpoint wants them as ``client_id`` / ``client_secret``.  They may
    sit at the top level or inside a nested object, so look in both.
    """
    body = _dict(payload)
    candidates: list[dict[str, Any]] = [body]
    for key in ("token", "tokens", "data", "device_token", "client", "result"):
        nested = body.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)

    out: dict[str, str] = {}
    for cand in candidates:
        app_id = str(
            cand.get("app_id")
            or cand.get("appId")
            or cand.get("client_id")
            or cand.get("clientId")
            or ""
        )
        app_secret = str(
            cand.get("app_secret")
            or cand.get("appSecret")
            or cand.get("client_secret")
            or cand.get("clientSecret")
            or ""
        )
        if app_id:
            out["client_id"] = app_id
        if app_secret:
            out["client_secret"] = app_secret
        if out:
            break
    return out


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    """Error raised for a non-ok REST envelope or an HTTP failure."""

    def __init__(self, status: int, payload: Any):
        body = _dict(payload)
        raw_err = body.get("error")
        err: dict[str, Any] = {}
        if isinstance(raw_err, dict):
            err = raw_err
        message = str(err.get("message") or "")
        if not message:
            desc = str(body.get("error_description") or body.get("errmsg") or "")
            if isinstance(raw_err, str):
                # The auth API puts a bare code here: {"error": "invalid_request"}.
                message = f"{raw_err}: {desc}" if desc else raw_err
            else:
                message = desc
        if not message and payload is not None and not isinstance(payload, dict):
            # The upstream answered with a bare string / list — surface it
            # instead of hiding it behind a generic HTTP status.
            message = str(payload)[:200]
        super().__init__(message or f"HTTP {status}")
        self.status = status
        self.code = str(err.get("code") or (raw_err if isinstance(raw_err, str) else ""))
        self.request_id = str(err.get("request_id") or "")
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
    def token_from_authorization(payload: Any) -> dict[str, Any] | None:
        """The token bundle carried by an authorization response, if any.

        The authorization step may hand the token out directly; when it only
        hands out an authorization code the caller has to run the exchange.
        """
        return _token_from_payload(payload)

    @staticmethod
    def client_credentials(payload: Any) -> dict[str, str]:
        """The client credentials carried by an authorization response."""
        return _client_credentials_from_payload(payload)

    @staticmethod
    def request_device_authorization() -> DeviceAuthorization:
        """Step 1 — ask for a device code.

        The official client posts a small JSON document that describes the
        caller (``cli_hostname`` / ``cli_ua`` / ``cli_version``); an empty
        form body is accepted by the server as well, but the JSON form is
        what the server is actually built for.
        """
        body = json.dumps(
            {
                "cli_hostname": str(uuid.uuid4()),
                "cli_ua": _DEFAULT_HEADERS["User-Agent"],
                "cli_version": CLI_VERSION,
            }
        ).encode("utf-8")
        status, _, raw = _request(
            AUTH_BASE, "POST", "/oauth/device?func=1", data=body, headers={"Content-Type": _JSON}
        )
        data = _json(raw)
        if not isinstance(data, dict) or not data.get("poll_url") or not data.get("input_code"):
            # Keep whatever the server answered: it may be a bare error string.
            raise ApiError(
                status,
                data or {"error": {"message": f"device authorization failed: {raw[:200]!r}"}},
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
    def poll_status(poll_url: str, *, timeout: int = POLL_TIMEOUT) -> dict[str, Any]:
        """Step 2 — long-poll for authorization.

        The official client issues a *GET* without a request body and lets the
        server hold the connection for ~20 s.  A GET is what the endpoint
        expects; the POST variant is kept as a fallback for proxies that
        reject GETs.
        """
        status, _, body = _request(None, "GET", poll_url, timeout=timeout)
        if status in (404, 405, 501):
            status, _, body = _request(
                None, "POST", poll_url, data=b"", headers={"Content-Type": _FORM}, timeout=timeout
            )
        data = _json(body)
        if isinstance(data, dict):
            return {"status": status, "body": data}
        # Not a JSON object — hand the raw payload back so the caller can
        # report something meaningful instead of silently hanging.
        raw = "" if data is None else str(data)[:200]
        return {"status": status, "body": {}, "raw": raw}

    @staticmethod
    def exchange_token(
        code: str,
        *,
        client_id: str = "",
        client_secret: str = "",
        grant_type: str = "authorization_code",
    ) -> dict[str, Any]:
        """Step 3 — trade an authorization code for tokens.

        ``POST /oauth/token`` only understands the form encoding
        ``grant_type`` + (``code`` | ``refresh_token``) + ``client_id``
        (+ ``client_secret``).  Any other key makes it answer with the
        generic "missing or malformed request parameters", which is what the
        previous implementation ran into for every single shape it tried.
        """
        params = {"grant_type": grant_type, "code": code}
        cid = client_id or CLIENT_ID
        csecret = client_secret or CLIENT_SECRET
        if cid:
            params["client_id"] = cid
        if csecret:
            params["client_secret"] = csecret

        status, _, raw = _request(
            AUTH_BASE,
            "POST",
            "/oauth/token",
            data=_form(params),
            headers={"Content-Type": _FORM},
        )
        data = _json(raw)
        token = _token_from_payload(data)
        if token:
            return token
        if status == 412:
            return {"pending": True, "status": status}
        err = ApiError(status, data)
        if _is_unsupported_shape(data):
            raise ApiError(
                status,
                {
                    "error": {
                        "code": "invalid_request",
                        "message": (
                            "token endpoint rejected the request shape "
                            f"(grant_type={grant_type}, client_id={cid or '<missing>'})"
                        ),
                    }
                },
            )
        raise err

    @staticmethod
    def refresh_token(
        refresh_token: str,
        *,
        client_id: str = "",
        client_secret: str = "",
    ) -> dict[str, Any]:
        """Exchange a refresh token for a fresh access token."""
        params = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        cid = client_id or CLIENT_ID
        csecret = client_secret or CLIENT_SECRET
        if cid:
            params["client_id"] = cid
        if csecret:
            params["client_secret"] = csecret

        status, _, body = _request(
            AUTH_BASE,
            "POST",
            "/oauth/token",
            data=_form(params),
            headers={"Content-Type": _FORM},
        )
        data = _json(body)
        token = _token_from_payload(data)
        if token:
            return {
                "access_token": token["access_token"],
                "refresh_token": token["refresh_token"] or refresh_token,
                "expires_in": token["expires_in"],
                "expires_at": token["expires_at"],
            }
        desc = str(_dict(data).get("error_description") or "")
        raise ApiError(
            status, data or {"error": {"message": desc or f"refresh failed (HTTP {status})"}}
        )

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
