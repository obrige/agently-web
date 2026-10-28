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


def test_api_error_uses_a_string_error_field() -> None:
    err = ApiError(400, {"err_code": -20011, "error": "invalid_request"})
    assert str(err) == "invalid_request"


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


# --------------------------------------------------------------------------- #
# The auth API does not always answer with a JSON object — an error reply can
# be a bare string. None of these may blow up with an AttributeError.
# --------------------------------------------------------------------------- #
def _stub_response(monkeypatch: pytest.MonkeyPatch, body: bytes, status: int = 200) -> None:
    """Make every upstream call answer with `body`."""

    def fake_request(base, method, path, **kwargs):
        return status, {}, body

    monkeypatch.setattr("agently.client._request", fake_request)


def test_api_error_survives_a_string_payload() -> None:
    err = ApiError(400, "invalid_input_code")
    assert err.status == 400
    assert str(err) == "invalid_input_code"
    assert err.code == ""


def test_api_error_survives_a_list_payload() -> None:
    err = ApiError(500, ["boom", "bang"])
    assert str(err) == "['boom', 'bang']"
    assert err.request_id == ""


def test_api_error_prefers_the_error_message() -> None:
    err = ApiError(400, {"error": {"message": "bad code"}})
    assert str(err) == "bad code"


def test_api_error_falls_back_to_error_description() -> None:
    assert str(ApiError(400, {"error_description": "missing parameter"})) == "missing parameter"
    assert str(ApiError(400, {"errmsg": "unsupported client"})) == "unsupported client"


def test_exchange_token_reports_a_non_object_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_response(monkeypatch, b'"invalid_input_code"')
    with pytest.raises(ApiError) as excinfo:
        client.Auth.exchange_token("ABCD")
    assert str(excinfo.value) == "invalid_input_code"


def test_refresh_token_reports_a_non_object_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_response(monkeypatch, b'"invalid_grant"')
    with pytest.raises(ApiError) as excinfo:
        client.Auth.refresh_token("rt")
    assert str(excinfo.value) == "invalid_grant"


def test_device_auth_reports_a_non_object_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_response(monkeypatch, b'"unsupported client"')
    with pytest.raises(ApiError) as excinfo:
        client.Auth.request_device_authorization()
    assert str(excinfo.value) == "unsupported client"


def test_poll_status_keeps_the_raw_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_response(monkeypatch, b'"pending"')
    result = client.Auth.poll_status("https://example.invalid/poll")
    assert result["body"] == {}
    assert result["raw"] == "pending"


def test_poll_status_returns_the_object_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_response(monkeypatch, b'{"status": "pending"}')
    result = client.Auth.poll_status("https://example.invalid/poll")
    assert result["body"] == {"status": "pending"}
    assert "raw" not in result


# --------------------------------------------------------------------------- #
# The device-flow protocol — shapes verified against the live server.
# --------------------------------------------------------------------------- #
def test_device_authorization_posts_the_official_json_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_request(base, method, path, **kwargs):
        seen["method"] = method
        seen["path"] = path
        seen["headers"] = kwargs.get("headers") or {}
        seen["data"] = kwargs.get("data") or b""
        body = (
            b'{"poll_url": "https://auth/oauth/device?func=2&device_code=dc_1",'
            b' "browser_url": "https://agent/page/oauth?user_code=uc_1",'
            b' "input_code": "ic_1", "expires_in": 600}'
        )
        return 200, {}, body

    monkeypatch.setattr("agently.client._request", fake_request)
    dev = client.Auth.request_device_authorization()

    assert seen["method"] == "POST"
    assert seen["path"] == "/oauth/device?func=1"
    assert seen["headers"]["Content-Type"] == "application/json"
    payload = json.loads(seen["data"])
    assert payload["cli_version"] == "1.0.18"
    assert payload["cli_ua"].startswith("agently-cli/")
    assert payload["cli_hostname"]
    assert dev.input_code == "ic_1"
    assert dev.device_code == "dc_1"
    assert dev.user_code == "uc_1"


def test_poll_status_uses_get(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_request(base, method, path, **kwargs):
        seen["method"] = method
        seen["path"] = path
        return 200, {}, b'{"status": "pending"}'

    monkeypatch.setattr("agently.client._request", fake_request)
    result = client.Auth.poll_status("https://auth/oauth/device?func=2&device_code=dc_1")

    assert seen["method"] == "GET"
    assert result["body"] == {"status": "pending"}


def test_poll_status_falls_back_to_post(monkeypatch: pytest.MonkeyPatch) -> None:
    methods: list[str] = []

    def fake_request(base, method, path, **kwargs):
        methods.append(method)
        if method == "GET":
            return 405, {}, b""
        return 200, {}, b'{"status": "pending"}'

    monkeypatch.setattr("agently.client._request", fake_request)
    result = client.Auth.poll_status("https://auth/poll")

    assert methods == ["GET", "POST"]
    assert result["body"] == {"status": "pending"}


def test_exchange_token_uses_the_verified_parameter_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_request(base, method, path, **kwargs):
        seen["path"] = path
        seen["headers"] = kwargs.get("headers") or {}
        seen["data"] = kwargs.get("data") or b""
        return 200, {}, b'{"access_token": "tok", "refresh_token": "ref", "expires_in": 60}'

    monkeypatch.setattr("agently.client._request", fake_request)
    result = client.Auth.exchange_token("ic_1", client_id="agently-cli")

    assert seen["path"] == "/oauth/token"
    assert seen["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    body = seen["data"].decode()
    assert "grant_type=authorization_code" in body
    assert "code=ic_1" in body
    assert "client_id=agently-cli" in body
    assert result["access_token"] == "tok"
    assert result["refresh_token"] == "ref"


def test_exchange_token_reports_the_rejected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"err_code": -20011, "error": "invalid_request"}'
    _stub_response(monkeypatch, body, status=401)
    with pytest.raises(ApiError) as excinfo:
        client.Auth.exchange_token("ic_1", client_id="agently-cli")
    message = str(excinfo.value)
    assert "rejected the request shape" in message
    assert "client_id=agently-cli" in message


def test_refresh_token_carries_the_client_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_request(base, method, path, **kwargs):
        seen["data"] = kwargs.get("data") or b""
        return 200, {}, b'{"access_token": "tok2", "refresh_token": "ref2", "expires_in": 60}'

    monkeypatch.setattr("agently.client._request", fake_request)
    result = client.Auth.refresh_token("ref", client_id="cid", client_secret="csec")

    body = seen["data"].decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=ref" in body
    assert "client_id=cid" in body
    assert "client_secret=csec" in body
    assert result["access_token"] == "tok2"


def test_token_from_authorization_finds_a_nested_bundle() -> None:
    token = client.Auth.token_from_authorization(
        {"status": "authorized", "token": {"access_token": "tok", "refresh_token": "ref"}}
    )
    assert token is not None
    assert token["access_token"] == "tok"
    assert token["refresh_token"] == "ref"


def test_token_from_authorization_reads_the_top_level_bundle() -> None:
    token = client.Auth.token_from_authorization(
        {"access_token": "tok", "refresh_token": "ref", "expires_in": 60, "app_id": "aid"}
    )
    assert token is not None
    assert token["expires_in"] == 60
    assert token["app_id"] == "aid"


def test_token_from_authorization_returns_none_for_a_pending_payload() -> None:
    assert client.Auth.token_from_authorization({"status": "pending"}) is None


def test_client_credentials_map_app_ids_to_client_ids() -> None:
    creds = client.Auth.client_credentials({"app_id": "aid", "app_secret": "asec"})
    assert creds == {"client_id": "aid", "client_secret": "asec"}
