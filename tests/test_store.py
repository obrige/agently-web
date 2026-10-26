"""Tests for :mod:`agently.store` — the on-disk account store."""

from __future__ import annotations

from pathlib import Path

import pytest

from agently.store import AccountStore


def test_create_pending_then_complete_login(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    assert account_id.startswith("acc_")
    assert store.get(account_id)["status"] == "pending"

    store.complete_login(account_id, {"accessToken": "t", "refreshToken": "r"})
    account = store.get(account_id)
    assert account["status"] == "active"
    assert account["accessToken"] == "t"
    assert account["refreshToken"] == "r"


def test_list_exposes_the_public_account_fields(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    store.complete_login(account_id, {"accessToken": "t"})
    profile = {"email": "a@b.c", "aliasId": "alias_1", "displayName": "A"}
    store.set_profile(account_id, profile)

    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["id"] == account_id
    assert listed[0]["email"] == "a@b.c"
    assert listed[0]["aliasId"] == "alias_1"
    assert listed[0]["displayName"] == "A"


def test_fail_login_records_the_error(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    store.fail_login(account_id, "denied")
    assert store.get(account_id)["status"] == "error"
    assert store.get(account_id)["error"] == "denied"


def test_update_tokens_rejects_an_unknown_account(data_dir: Path) -> None:
    store = AccountStore()
    with pytest.raises(KeyError):
        store.update_tokens("nope", {"accessToken": "t"})


def test_update_tokens_refreshes_the_stored_token(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    store.update_tokens(account_id, {"accessToken": "one"})
    store.update_tokens(account_id, {"accessToken": "two"})
    assert store.get(account_id)["accessToken"] == "two"


def test_remove_drops_the_account_and_its_state(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    store.upsert_draft(account_id, {"subject": "hi"})
    store.set_signature(account_id, {"plain": "sig"})
    store.star(account_id, "msg_1")
    store.add_contact(account_id, "a@b.c", "AB")

    store.remove(account_id)

    assert store.get(account_id) is None
    assert store.list_drafts(account_id) == []
    assert store.list_stars(account_id) == []
    assert store.list_contacts(account_id) == []
    assert store.get_signature(account_id) == {"plain": "", "html": ""}


def test_drafts_are_upserted_and_kept(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    first = store.upsert_draft(account_id, {"subject": "first"})
    second = store.upsert_draft(account_id, {"subject": "second"})
    assert first["draftId"].startswith("drf_")
    assert second["draftId"].startswith("drf_")
    assert len(store.list_drafts(account_id)) == 2

    again = store.upsert_draft(account_id, {"draftId": first["draftId"], "subject": "x"})
    assert again["draftId"] == first["draftId"]
    assert len(store.list_drafts(account_id)) == 2
    assert store.get_draft(account_id, first["draftId"])["subject"] == "x"


def test_delete_draft_removes_it(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    draft = store.upsert_draft(account_id, {"subject": "hi"})
    assert store.delete_draft(account_id, draft["draftId"]) is True
    assert store.delete_draft(account_id, draft["draftId"]) is False
    assert store.get_draft(account_id, draft["draftId"]) is None


def test_signature_round_trip(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    assert store.get_signature(account_id) == {"plain": "", "html": ""}
    saved = store.set_signature(account_id, {"plain": "hi", "html": "<p>hi</p>"})
    assert saved["plain"] == "hi"
    assert saved["html"] == "<p>hi</p>"
    assert store.get_signature(account_id)["plain"] == "hi"


def test_stars_are_unique_and_sorted(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    assert store.star(account_id, "msg_b") is True
    assert store.star(account_id, "msg_a") is True
    assert store.star(account_id, "msg_b") is False
    assert store.list_stars(account_id) == ["msg_a", "msg_b"]
    assert store.unstar(account_id, "msg_a") is True
    assert store.unstar(account_id, "msg_a") is False
    assert store.list_stars(account_id) == ["msg_b"]


def test_contacts_are_lowercased_and_sorted(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    contact = store.add_contact(account_id, " Bob@Example.COM ", "Bob")
    assert contact["email"] == "bob@example.com"
    assert contact["name"] == "Bob"

    store.add_contact(account_id, "alice@example.com")
    emails = [c["email"] for c in store.list_contacts(account_id)]
    assert emails == ["alice@example.com", "bob@example.com"]
    assert store.remove_contact(account_id, "BOB@example.com") is True
    assert store.remove_contact(account_id, "bob@example.com") is False


def test_the_store_survives_a_reopen(data_dir: Path) -> None:
    store = AccountStore()
    account_id = store.create_pending()
    store.complete_login(account_id, {"accessToken": "t"})

    reopened = AccountStore()
    assert reopened.get(account_id)["accessToken"] == "t"
