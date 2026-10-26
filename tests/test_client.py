"""Tests for :mod:`agently.client` — encoding helpers and the API envelope."""

from __future__ import annotations

import gzip
import json

import pytest

from agently import client
from agently.client import AgentlyApi, ApiError, DeviceAuthorization


def test_esc_escapes_everything_but_the_unreserved_characters() -> None:
    assert client._esc("alias@example.com") == "alias%40example.com"
    assert client._esc("a/b c") == "a%2Fb%20c"
    assert client._esc("plain") == "plain"


def test_form_encodes_pairs_and_drops_none() -> None:
    assert client.formEncode({"a": "1", "b": None, "c": "x y"}) == b"a=1&c=x+y"
    assert client.formEncode({}) == b""


def test_json_returns_none_for_unparsable_bodies() -> None:
    assert client._json(b"") is None
    assert client._json(b"not json") is None
    assert client._json(json.dumps({"ok": True}).encode()) == {"ok": True}


def test_decompress_only_unwraps_gzip() -> None:
    payload = b"hello"
    assert client._decompress(gzip.compress(payload), "gzip") == payload
    assert client._decompress(payload, "gzip") == payload
    assert client._decompress(payload, "") == payload
    assert client._decompress(payload, "br") == payload


def test_decompress_leaves_broken_gzip_alone() -> None:
    assert client._decompress(b"not gzip", "gzip") == b"not gzip"


def test_api_error_carries_the_error_envelope() -> None:
    payload = {"error": {"code": "AUTH", "message": "boom", "request_id": "r1"}}
    err = ApiError(412, payload)
    assert err.status == 412
    assert err.code == "AUTH"
    assert str(err) == "boom"
    assert err.request_id == "r1"


def test_api_error_falls_back_to_the_http_status() -> None:
    err = ApiError(500, None)
    assert str(err) == "HTTP 500"
    assert err.code == ""
    assert err.request_id == ""


def test_device_authorization_exposes_every_field() -> None:
    dev = DeviceAuthorization(input_code="ABCD", poll_url="https://x/poll")
    assert dev.as_dict()["input_code"] == "ABCD"
    assert dev.as_dict()["poll_url"] == "https://x/poll"
    assert dev.as_dict()["scan_url"] is None


def test_api_refuses_to_call_without_a_token() -> None:
    api = AgentlyApi(lambda: None)
    with pytest.raises(ApiError) as excinfo:
        api.me()
    assert excinfo.value.status == 401


def test_api_sends_the_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_request(base, method, path, **kwargs):
        seen["base"] = base
        seen["method"] = method
        seen["path"] = path
        seen["headers"] = kwargs.get("headers") or {}
        body = json.dumps({"ok": True, "data": {"email": "a@b.c"}}).encode()
        return 200, {}, body

    monkeypatch.setattr("agently.client._request", fake_request)
    api = AgentlyApi(lambda: "token-123")
    assert api.me() == {"email": "a@b.c"}
    assert seen["headers"] == {"Authorization": "Bearer token-123"}
