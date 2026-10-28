"""Response normalisation — flattens the many shapes the API may return."""

from __future__ import annotations

from typing import Any


def _pick(src: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = src.get(k)
        if v is not None and v != "":
            return v
    return None


def normalise_me(me: Any) -> dict[str, Any]:
    """Flatten whatever /v1/me returns into {email, aliasId, displayName, aliases}."""
    out: dict[str, Any] = {"email": "", "aliasId": "", "displayName": "", "aliases": []}
    if not isinstance(me, dict):
        return out

    out["email"] = _pick(me, "email", "mail", "address", "mail_address", "qq_mail") or ""
    out["aliasId"] = _pick(me, "alias_id", "aliasId", "default_alias_id", "id") or ""
    out["displayName"] = (
        _pick(me, "display_name", "displayName", "name", "nickname", "nick") or out["email"]
    )

    raw = me.get("aliases") or me.get("data") or []
    if isinstance(raw, list):
        aliases: list[dict[str, Any]] = []
        for a in raw:
            if isinstance(a, str):
                aliases.append({"aliasId": a, "email": a, "displayName": a})
            elif isinstance(a, dict):
                alias_id = _pick(a, "alias_id", "aliasId", "id") or ""
                if not alias_id:
                    continue
                aliases.append(
                    {
                        "aliasId": alias_id,
                        "email": _pick(a, "email", "address", "alias_id") or "",
                        "displayName": _pick(a, "display_name", "name", "email") or "",
                    }
                )
        out["aliases"] = aliases

    if not out["aliasId"] and out["aliases"]:
        out["aliasId"] = out["aliases"][0]["aliasId"]
    return out


def messages_of(data: Any) -> list[dict[str, Any]]:
    """Pull the message array out of a list/search response."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "messages", "items"):
            v = data.get(key)
            if isinstance(v, list):
                return v
    return []


def pagination_of(data: Any) -> dict[str, Any]:
    p = data.get("pagination") if isinstance(data, dict) else None
    p = p if isinstance(p, dict) else {}
    nxt = p.get("next_cursor") or p.get("nextCursor")
    return {"nextCursor": nxt, "hasMore": p.get("has_more") is True or bool(nxt)}
