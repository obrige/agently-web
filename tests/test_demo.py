"""Tests for :mod:`agently.demo` — the seed mailbox used by demo mode."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agently.demo import ApiErrorLike, DemoApi, DemoStore, _parse_ts, _strip_tags


def test_parse_ts_accepts_epoch_milliseconds() -> None:
    assert _parse_ts(1700000000000) == 1700000000000.0


def test_parse_ts_accepts_iso_timestamps() -> None:
    expected = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
    assert _parse_ts("2024-01-01T00:00:00+00:00") == expected


def test_strip_tags_removes_markup() -> None:
    assert _strip_tags("<p>hello</p>").strip() == "hello"
    assert "#" not in _strip_tags("#tag")
    assert "*" not in _strip_tags("*bold*")


def test_demo_api_serves_the_seed_inbox() -> None:
    api = DemoApi()
    result = api.list_messages("alias_demo")
    assert result["pagination"]["has_more"] is False
    assert len(result["data"]) > 0
    assert all(m["dir"] == "inbox" for m in result["data"])


def test_demo_api_keeps_the_folders_apart() -> None:
    api = DemoApi()
    sent = api.list_messages("alias_demo", folder="sent")
    trash = api.list_messages("alias_demo", folder="trash")
    assert all(m["dir"] == "sent" for m in sent["data"])
    assert all(m.get("deleted") for m in trash["data"])


def test_demo_api_starring_round_trip() -> None:
    api = DemoApi()
    assert api.star_message("msg_001") is True
    assert api.star_message("msg_001") is False
    assert "msg_001" in api.list_stars()
    assert api.unstar_message("msg_001") is True
    assert api.unstar_message("msg_001") is False


def test_demo_api_search_matches_the_body() -> None:
    api = DemoApi()
    result = api.search_messages("alias_demo", "github")
    ids = [m["message_id"] for m in result["data"]]
    assert "msg_001" in ids


def test_demo_api_requires_a_recipient() -> None:
    api = DemoApi()
    with pytest.raises(ApiErrorLike):
        api.send_message("alias_demo", {"to_recipients": []})


def test_demo_api_asks_for_confirmation_before_sending() -> None:
    api = DemoApi()
    payload = {"to_recipients": [{"email": "friend@example.com"}]}
    result = api.send_message("alias_demo", payload)
    assert result["confirmation_required"] is True
    assert result["confirmation_token"].startswith("demo_ct_")


def test_demo_store_creates_a_single_demo_account() -> None:
    store = DemoStore()
    account_id = store.create_pending()
    assert account_id == "acc_demo"
    assert store.get(account_id)["status"] == "pending"
    assert store.list()[0]["email"] == "agent@qq.com"
