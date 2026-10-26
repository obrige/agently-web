"""Account store — persists OAuth credentials, profile and per-account
state (drafts, signatures, stars, contacts) on disk.

The file layout under $AGENTLY_WEB_DATA_DIR:

    accounts.json       — one record per account id
    drafts.json         — {accountId: {draftId: {...}}}
    signatures.json     — {accountId: {plain: "...", html: "..."}}
    stars.json          — {accountId: [message_id, ...]}
    contacts.json       — {accountId: {email: {name, email, addedAt}}}
"""

from __future__ import annotations

import builtins
import contextlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(
    os.environ.get("AGENTLY_WEB_DATA_DIR", Path(__file__).resolve().parent.parent / ".data")
)

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
DRAFTS_FILE = DATA_DIR / "drafts.json"
SIGNATURES_FILE = DATA_DIR / "signatures.json"
STARS_FILE = DATA_DIR / "stars.json"
CONTACTS_FILE = DATA_DIR / "contacts.json"


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class AccountStore:
    def __init__(self) -> None:
        self._accounts: dict[str, Any] = _load(ACCOUNTS_FILE, {})
        self._drafts: dict[str, Any] = _load(DRAFTS_FILE, {})
        self._signatures: dict[str, Any] = _load(SIGNATURES_FILE, {})
        self._stars: dict[str, Any] = _load(STARS_FILE, {})
        self._contacts: dict[str, Any] = _load(CONTACTS_FILE, {})

    # ---- accounts ---- #
    def _flush_accounts(self) -> None:
        _save(ACCOUNTS_FILE, self._accounts)

    def list(self) -> builtins.list[dict[str, Any]]:
        return [
            {
                "id": acc_id,
                "email": a.get("email", ""),
                "aliasId": a.get("aliasId", ""),
                "displayName": a.get("displayName") or a.get("email") or acc_id,
                "addedAt": a.get("addedAt", 0),
            }
            for acc_id, a in self._accounts.items()
        ]

    def get(self, account_id: str) -> dict[str, Any] | None:
        return self._accounts.get(account_id)

    def create_pending(self) -> str:
        account_id = "acc_" + secrets.token_hex(8)
        self._accounts[account_id] = {"addedAt": int(time.time() * 1000), "status": "pending"}
        self._flush_accounts()
        return account_id

    def complete_login(self, account_id: str, tokens: dict[str, Any]) -> dict[str, Any]:
        acc = self._accounts.setdefault(account_id, {})
        acc.update(tokens)
        acc["status"] = "active"
        acc.pop("error", None)
        self._flush_accounts()
        return dict(acc)

    def fail_login(self, account_id: str, message: str) -> None:
        acc = self._accounts.get(account_id)
        if acc:
            acc["status"] = "error"
            acc["error"] = message
            self._flush_accounts()

    def update_tokens(self, account_id: str, tokens: dict[str, Any]) -> None:
        acc = self._accounts.get(account_id)
        if acc is None:
            raise KeyError(f"unknown account {account_id}")
        acc.update(tokens)
        self._flush_accounts()

    def set_profile(self, account_id: str, profile: dict[str, Any]) -> None:
        acc = self._accounts.get(account_id)
        if acc is None:
            return
        acc["email"] = profile.get("email") or acc.get("email", "")
        acc["aliasId"] = profile.get("aliasId") or acc.get("aliasId", "")
        acc["displayName"] = profile.get("displayName") or acc.get("displayName", "")
        acc["profile"] = profile
        self._flush_accounts()

    def remove(self, account_id: str) -> None:
        self._accounts.pop(account_id, None)
        self._drafts.pop(account_id, None)
        self._signatures.pop(account_id, None)
        self._stars.pop(account_id, None)
        self._contacts.pop(account_id, None)
        self._flush_accounts()
        _save(DRAFTS_FILE, self._drafts)
        _save(SIGNATURES_FILE, self._signatures)
        _save(STARS_FILE, self._stars)
        _save(CONTACTS_FILE, self._contacts)

    # ---- drafts ---- #
    def list_drafts(self, account_id: str) -> builtins.list[dict[str, Any]]:
        return sorted(
            self._drafts.get(account_id, {}).values(),
            key=lambda d: d.get("updatedAt", 0),
            reverse=True,
        )

    def get_draft(self, account_id: str, draft_id: str) -> dict[str, Any] | None:
        d = self._drafts.get(account_id, {}).get(draft_id)
        return dict(d) if d else None

    def upsert_draft(self, account_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        bucket = self._drafts.setdefault(account_id, {})
        if not draft.get("draftId"):
            draft["draftId"] = "drf_" + secrets.token_hex(8)
        draft["updatedAt"] = int(time.time() * 1000)
        bucket[draft["draftId"]] = draft
        _save(DRAFTS_FILE, self._drafts)
        return draft

    def delete_draft(self, account_id: str, draft_id: str) -> bool:
        bucket = self._drafts.get(account_id)
        if not bucket or draft_id not in bucket:
            return False
        bucket.pop(draft_id)
        _save(DRAFTS_FILE, self._drafts)
        return True

    # ---- signatures ---- #
    def get_signature(self, account_id: str) -> dict[str, Any]:
        return self._signatures.get(account_id) or {"plain": "", "html": ""}

    def set_signature(self, account_id: str, sig: dict[str, Any]) -> dict[str, Any]:
        out = {
            "plain": str(sig.get("plain", "")),
            "html": str(sig.get("html", "")),
            "updatedAt": int(time.time() * 1000),
        }
        self._signatures[account_id] = out
        _save(SIGNATURES_FILE, self._signatures)
        return out

    # ---- stars ---- #
    def list_stars(self, account_id: str) -> builtins.list[str]:
        return sorted(self._stars.get(account_id, []))

    def star(self, account_id: str, message_id: str) -> bool:
        bucket = self._stars.setdefault(account_id, [])
        if message_id in bucket:
            return False
        bucket.append(message_id)
        _save(STARS_FILE, self._stars)
        return True

    def unstar(self, account_id: str, message_id: str) -> bool:
        bucket = self._stars.get(account_id)
        if not bucket or message_id not in bucket:
            return False
        bucket.remove(message_id)
        _save(STARS_FILE, self._stars)
        return True

    # ---- contacts ---- #
    def list_contacts(self, account_id: str) -> builtins.list[dict[str, Any]]:
        bucket = self._contacts.get(account_id, {})
        return sorted(
            [
                {"name": c.get("name", ""), "email": email, "addedAt": c.get("addedAt", 0)}
                for email, c in bucket.items()
            ],
            key=lambda c: c["email"],
        )

    def add_contact(self, account_id: str, email: str, name: str = "") -> dict[str, Any]:
        email = email.strip().lower()
        bucket = self._contacts.setdefault(account_id, {})
        existing = bucket.get(email, {})
        contact = {
            "name": name or existing.get("name", ""),
            "email": email,
            "addedAt": existing.get("addedAt", int(time.time() * 1000)),
        }
        bucket[email] = contact
        _save(CONTACTS_FILE, self._contacts)
        return contact

    def remove_contact(self, account_id: str, email: str) -> bool:
        bucket = self._contacts.get(account_id)
        email = email.strip().lower()
        if not bucket or email not in bucket:
            return False
        bucket.pop(email)
        _save(CONTACTS_FILE, self._contacts)
        return True
