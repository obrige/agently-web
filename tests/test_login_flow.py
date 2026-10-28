"""End-to-end login flow against a local fake Agently service.

The fake speaks the wire format that was captured from the official
``@tencent-qqmail/agently-cli`` v1.0.18 and verified against the live
server:

* ``POST /oauth/device?func=1`` — JSON body with cli_hostname / cli_ua /
  cli_version.
* ``GET <poll_url>`` — long poll, no request body.
* ``POST /oauth/token`` — form encoded; the endpoint accepts *only*
  ``grant_type`` + (``code`` | ``refresh_token``) + ``client_id``
  (+ ``client_secret``) and answers the generic ``invalid_request`` for
  everything else.

The test drives the real ``server.start_login()`` / ``poll_login()`` code
path, so a regression in the protocol handling fails here.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

# The account store writes to disk when it is imported — keep the test out
# of the repository's .data/ directory.
os.environ["AGENTLY_WEB_DATA_DIR"] = tempfile.mkdtemp(prefix="agently-web-test-")
os.environ.pop("AGENTLY_WEB_DEMO", None)

import server  # noqa: E402
from agently import client  # noqa: E402


class FakeAgently:
    """A stand-in for auth.agent.qq.com + api.agent.qq.com."""

    def __init__(self, *, poll_payload: str = "token") -> None:
        self.poll_payload = poll_payload
        self.requests: list[dict[str, Any]] = []
        self.polls = 0
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None

    # -- lifecycle -------------------------------------------------------- #
    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # noqa: D102, ARG002
                pass

            def _json(self, status: int, payload: Any) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _record(self, raw: bytes) -> None:
                with outer._lock:
                    outer.requests.append(
                        {
                            "method": self.command,
                            "path": self.path,
                            "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": raw.decode("utf-8", "replace"),
                        }
                    )

            def do_GET(self) -> None:  # noqa: N802
                self._record(b"")
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/oauth/device":
                    with outer._lock:
                        outer.polls += 1
                        first = outer.polls == 1
                    if first:
                        self._json(200, {"status": "pending"})
                    elif outer.poll_payload == "token":
                        self._json(
                            200,
                            {
                                "status": "authorized",
                                "access_token": "at_test",
                                "refresh_token": "rt_test",
                                "expires_in": 3600,
                                "expires_at": int(time.time()) + 3600,
                                "app_id": "app_1",
                                "app_secret": "sec_1",
                            },
                        )
                    else:
                        # The variant where the poll only hands out a code
                        # and the client credentials.
                        self._json(
                            200,
                            {
                                "status": "authorized",
                                "code": "code_test",
                                "app_id": "app_1",
                                "app_secret": "sec_1",
                            },
                        )
                    return
                if parsed.path == "/v1/me":
                    self._json(200, {"ok": True, "data": {"email": "bot@qq.com"}})
                    return
                self._json(404, {"ok": False, "error": {"message": "not found"}})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                self._record(raw)
                parsed = urllib.parse.urlparse(self.path)

                if parsed.path == "/oauth/device":
                    payload = json.loads(raw or b"{}")
                    assert payload.get("cli_version"), "device request must describe the caller"
                    base = outer.base
                    self._json(
                        200,
                        {
                            "scan_url": "",
                            "poll_url": f"{base}/oauth/device?func=2&device_code=dc_test",
                            "browser_url": f"{base}/page/oauth?oauth_type=device&user_code=uc_test",
                            "input_code": "ic_test",
                            "expires_in": 600,
                        },
                    )
                    return

                if parsed.path == "/oauth/token":
                    form = dict(urllib.parse.parse_qsl(raw.decode("utf-8", "replace")))
                    # The real endpoint rejects every unknown key.
                    allowed = {"grant_type", "code", "refresh_token", "client_id", "client_secret"}
                    if not form or not set(form) <= allowed:
                        self._json(
                            401,
                            {
                                "err_code": -20011,
                                "error": "invalid_request",
                                "error_description": "missing or malformed request parameters",
                            },
                        )
                        return
                    if "client_id" not in form:
                        self._json(
                            401,
                            {
                                "err_code": -20011,
                                "error": "invalid_request",
                                "error_description": "missing or malformed request parameters",
                            },
                        )
                        return
                    self._json(
                        200,
                        {
                            "access_token": "at_exchanged",
                            "refresh_token": "rt_exchanged",
                            "expires_in": 3600,
                            "expires_at": int(time.time()) + 3600,
                            "app_id": "app_1",
                            "app_secret": "sec_1",
                        },
                    )
                    return

                self._json(404, {"ok": False, "error": {"message": "not found"}})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self.base

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def base(self) -> str:
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    # -- helpers ---------------------------------------------------------- #
    def find(self, needle: str) -> list[dict[str, Any]]:
        with self._lock:
            return [r for r in self.requests if needle in r["path"]]


@pytest.fixture
def fake() -> FakeAgently:
    svc = FakeAgently()
    svc.start()
    yield svc
    svc.stop()


def _run_login(monkeypatch: pytest.MonkeyPatch, svc: FakeAgently) -> dict[str, Any]:
    monkeypatch.setattr(client, "AUTH_BASE", svc.base)
    monkeypatch.setattr(client, "API_BASE", svc.base)
    entry = server.start_login()
    deadline = time.time() + 30
    while time.time() < deadline:
        current = server.LOGINS[entry["loginId"]]
        if current["status"] in ("complete", "error"):
            return current
        time.sleep(0.05)
    raise AssertionError("login did not finish in time")


def test_login_completes_when_the_poll_hands_out_the_token(
    monkeypatch: pytest.MonkeyPatch, fake: FakeAgently
) -> None:
    entry = _run_login(monkeypatch, fake)
    assert entry["status"] == "complete", entry.get("error")

    acc = server.store.get(entry["accountId"])
    assert acc is not None
    assert acc["accessToken"] == "at_test"
    assert acc["refreshToken"] == "rt_test"
    # The client credentials are kept for the refresh call.
    assert acc["clientId"] == "app_1"
    assert acc["clientSecret"] == "sec_1"

    # The device request is the official JSON shape ...
    device = fake.find("/oauth/device")[0]
    assert device["method"] == "POST"
    assert device["headers"]["content-type"] == "application/json"
    payload = json.loads(device["body"])
    assert payload["cli_version"] == "1.0.18"
    assert payload["cli_ua"].startswith("agently-cli/")
    assert payload["cli_hostname"]

    # ... and the poll is a GET.
    polls = [r for r in fake.requests if "func=2" in r["path"]]
    assert polls, "the client must poll the authorization status"
    assert all(p["method"] == "GET" for p in polls)

    # The token was already in the poll payload — no token exchange needed.
    assert not fake.find("/oauth/token")


def test_login_exchanges_the_code_when_the_poll_only_hands_one_out(
    monkeypatch: pytest.MonkeyPatch, fake: FakeAgently
) -> None:
    fake.poll_payload = "code"
    entry = _run_login(monkeypatch, fake)
    assert entry["status"] == "complete", entry.get("error")

    acc = server.store.get(entry["accountId"])
    assert acc["accessToken"] == "at_exchanged"
    assert acc["refreshToken"] == "rt_exchanged"

    exchange = fake.find("/oauth/token")
    assert len(exchange) == 1
    body = exchange[0]["body"]
    assert exchange[0]["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert "grant_type=authorization_code" in body
    assert "code=code_test" in body
    # The client credentials come from the authorization response.
    assert "client_id=app_1" in body
    assert "client_secret=sec_1" in body


def test_exchange_without_a_client_id_is_reported(
    monkeypatch: pytest.MonkeyPatch, fake: FakeAgently
) -> None:
    """A token endpoint that does not understand the request must surface."""
    monkeypatch.setattr(client, "AUTH_BASE", fake.base)
    monkeypatch.setattr(client, "CLIENT_ID", "")
    monkeypatch.setattr(client, "CLIENT_SECRET", "")

    with pytest.raises(client.ApiError) as excinfo:
        client.Auth.exchange_token("code_test")
    assert "rejected the request shape" in str(excinfo.value)

    # The request that was sent is the one the endpoint does not understand.
    sent = fake.find("/oauth/token")
    assert len(sent) == 1
    assert "grant_type=authorization_code" in sent[0]["body"]
    assert "client_id" not in sent[0]["body"]
