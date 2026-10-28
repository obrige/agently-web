"""Tests for :mod:`agently.normalize` — the response-flattening helpers."""

from __future__ import annotations

from agently.normalize import messages_of, normalise_me, pagination_of

EMPTY_PROFILE = {"email": "", "aliasId": "", "displayName": "", "aliases": []}


def test_normalise_me_rejects_non_dict_payloads() -> None:
    assert normalise_me(None) == EMPTY_PROFILE
    assert normalise_me("nope") == EMPTY_PROFILE
    assert normalise_me([1, 2]) == EMPTY_PROFILE


def test_normalise_me_picks_the_first_populated_field() -> None:
    out = normalise_me({"mail": "agent@qq.com", "display_name": "Agent"})
    assert out["email"] == "agent@qq.com"
    assert out["displayName"] == "Agent"
    assert out["aliasId"] == ""


def test_normalise_me_falls_back_to_the_email_for_the_display_name() -> None:
    out = normalise_me({"email": "agent@qq.com"})
    assert out["displayName"] == "agent@qq.com"


def test_normalise_me_expands_string_aliases() -> None:
    out = normalise_me({"email": "agent@qq.com", "aliases": ["b@qq.com"]})
    expected = {"aliasId": "b@qq.com", "email": "b@qq.com", "displayName": "b@qq.com"}
    assert out["aliases"] == [expected]
    assert out["aliasId"] == "b@qq.com"


def test_normalise_me_normalises_dict_aliases() -> None:
    alias = {"alias_id": "alias_1", "email": "b@qq.com", "name": "Billing"}
    out = normalise_me({"email": "agent@qq.com", "aliases": [alias]})
    expected = {"aliasId": "alias_1", "email": "b@qq.com", "displayName": "Billing"}
    assert out["aliases"] == [expected]
    assert out["aliasId"] == "alias_1"


def test_normalise_me_drops_aliases_without_an_id() -> None:
    out = normalise_me({"email": "agent@qq.com", "aliases": [{"email": "b@qq.com"}]})
    assert out["aliases"] == []
    assert out["aliasId"] == ""


def test_messages_of_finds_the_message_array() -> None:
    assert messages_of(None) == []
    assert messages_of([{"id": 1}]) == [{"id": 1}]
    assert messages_of({"data": [{"id": 2}]}) == [{"id": 2}]
    assert messages_of({"messages": [{"id": 3}]}) == [{"id": 3}]
    assert messages_of({"items": [{"id": 4}]}) == [{"id": 4}]
    assert messages_of({"unexpected": "shape"}) == []


def test_pagination_of_reports_the_next_cursor() -> None:
    page = {"pagination": {"next_cursor": "abc"}}
    assert pagination_of(page) == {"nextCursor": "abc", "hasMore": True}


def test_pagination_of_reads_the_camel_case_cursor() -> None:
    page = {"pagination": {"nextCursor": "abc"}}
    assert pagination_of(page) == {"nextCursor": "abc", "hasMore": True}


def test_pagination_of_handles_missing_pagination() -> None:
    empty = {"nextCursor": None, "hasMore": False}
    assert pagination_of(None) == empty
    assert pagination_of({}) == empty
    assert pagination_of({"pagination": {}}) == empty


def test_pagination_of_reports_has_more() -> None:
    page = {"pagination": {"has_more": True}}
    assert pagination_of(page) == {"nextCursor": None, "hasMore": True}
