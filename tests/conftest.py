"""Shared pytest fixtures for the agently-web test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from agently import store as store_module


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the on-disk account store at a throw-away directory."""
    monkeypatch.setattr(store_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store_module, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(store_module, "DRAFTS_FILE", tmp_path / "drafts.json")
    monkeypatch.setattr(store_module, "SIGNATURES_FILE", tmp_path / "signatures.json")
    monkeypatch.setattr(store_module, "STARS_FILE", tmp_path / "stars.json")
    monkeypatch.setattr(store_module, "CONTACTS_FILE", tmp_path / "contacts.json")
    return tmp_path
