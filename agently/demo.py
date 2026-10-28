"""Demo mode — serves realistic seed mail so the UI can be exercised without
live Agently credentials. Activated with AGENTLY_WEB_DEMO=1.
"""

from __future__ import annotations

import builtins
import re
import time
from typing import Any, cast

NOW = time.time() * 1000
DAY = 86_400_000

DEMO_PROFILE: dict[str, Any] = {
    "email": "agent@qq.com",
    "aliasId": "alias_demo",
    "displayName": "Agently Demo",
    "profile": {
        "email": "agent@qq.com",
        "aliasId": "alias_demo",
        "displayName": "Agently Demo",
        "aliases": [
            {"aliasId": "alias_demo", "email": "agent@qq.com", "displayName": "主邮箱"},
            {"aliasId": "alias_billing", "email": "billing@qq.com", "displayName": "账单"},
            {"aliasId": "alias_news", "email": "news@qq.com", "displayName": "订阅"},
        ],
    },
}


def _seed() -> list[dict[str, Any]]:
    return [
        {
            "message_id": "msg_001",
            "from": {"name": "GitHub", "email": "noreply@github.com"},
            "to": [{"name": "Agently Demo", "email": "agent@qq.com"}],
            "subject": "[agently-web] Your build succeeded",
            "snippet": "Continuous integration has passed for commit a3f91c2 on branch main.",
            "body": (
                "## Build #482 — succeeded\n\n"
                "All checks passed on **main** at commit `a3f91c2`.\n\n"
                "| Step | Duration | Status |\n|---|---|---|\n| install | 18s | ok |\n"
                "| lint | 6s | ok |\n| test (312) | 41s | ok |\n| build | 22s | ok |\n\n"
                "[View the full log](https://example.com/builds/482)\n\n— The GitHub Actions team"
            ),
            "body_format": "MARKDOWN",
            "created_at": int(NOW - 2 * 3600 * 1000),
            "is_read": False,
            "attachments": [],
            "dir": "inbox",
        },
        {
            "message_id": "msg_002",
            "from": {"name": "产品团队", "email": "pm@tencent.com"},
            "to": [{"email": "agent@qq.com"}],
            "cc": [{"email": "design@tencent.com"}],
            "subject": "本周产品评审会议纪要",
            "snippet": "会议时间：周四下午 3 点。议题包括 Q3 路线图、邮箱 Agent 化改造方案…",
            "body": (
                "各位好，\n\n本周产品评审会议纪要如下：\n\n"
                "1. **Q3 路线图** — 确认以「邮箱 Agent 化」为核心主线\n"
                "2. **Agently Web 客户端** — 进入设计评审阶段\n"
                "3. **开放协议** — 讨论是否对外开放 REST API\n\n"
                "下次会议：周四下午 3 点，会议室 A。\n\n谢谢！\n产品团队"
            ),
            "body_format": "PLAIN",
            "created_at": int(NOW - 6 * 3600 * 1000),
            "is_read": False,
            "attachments": [
                {
                    "attachment_id": "att_101",
                    "filename": "会议纪要.pdf",
                    "size": 284160,
                    "content_type": "application/pdf",
                    "content_type_description": "PDF 文档",
                },
                {
                    "attachment_id": "att_102",
                    "filename": "Q3路线图.xlsx",
                    "size": 51200,
                    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "content_type_description": "Excel 工作簿",
                },
            ],
            "has_attachments": True,
            "attachment_count": 2,
            "dir": "inbox",
        },
        {
            "message_id": "msg_003",
            "from": {"name": "QQ 邮箱团队", "email": "service@qq.com"},
            "to": [{"email": "agent@qq.com"}],
            "subject": "欢迎使用 Agently — Agent 原生邮箱",
            "snippet": "你的专属 Agent 邮箱已开通。现在可以让 AI 助手帮你收发和管理邮件。",
            "body": (
                "<h2>欢迎使用 Agently</h2><p>你的专属 <strong>Agent 原生邮箱</strong> 已开通。</p>"
                "<ul><li>让 AI 助手帮你撰写和发送邮件</li><li>自动整理和分类收件箱</li>"
                "<li>通过 OAuth 安全授权第三方 Agent</li></ul>"
                '<p style="color:#6b7280">此邮件由系统自动发送，请勿直接回复。</p>'
            ),
            "body_format": "HTML",
            "created_at": int(NOW - 1 * DAY),
            "is_read": True,
            "attachments": [],
            "dir": "inbox",
            "starred": True,
        },
        {
            "message_id": "msg_004",
            "from": {"name": "云服务账单", "email": "billing@tencent.com"},
            "to": [{"email": "agent@qq.com"}],
            "subject": "【账单】2026 年 10 月云服务费用清单",
            "snippet": "本月消费合计 ¥1,286.40。主要构成：CDN 流量、对象存储、函数调用。",
            "body": (
                "尊敬的客户：\n\n您 2026 年 10 月的云服务费用清单已生成。\n\n"
                "- CDN 流量：¥682.10\n- 对象存储：¥318.20\n- 函数调用：¥286.10\n\n"
                "**合计：¥1,286.40**\n\n账单将在 3 个工作日内自动从余额扣划。"
            ),
            "body_format": "PLAIN",
            "created_at": int(NOW - 2 * DAY),
            "is_read": True,
            "attachments": [
                {
                    "attachment_id": "att_103",
                    "filename": "invoice-2026-10.pdf",
                    "size": 97280,
                    "content_type": "application/pdf",
                }
            ],
            "has_attachments": True,
            "attachment_count": 1,
            "dir": "inbox",
        },
        {
            "message_id": "msg_005",
            "from": {"name": "Agently Demo", "email": "agent@qq.com"},
            "to": [{"name": "张三", "email": "zhangsan@example.com"}],
            "subject": "关于下周技术分享的安排",
            "snippet": "我计划分享 Agently 协议的逆向分析，大约 40 分钟，包含现场演示。",
            "body": (
                "张三：\n\n下周的技术分享我打算讲 Agently 协议的逆向分析，大纲：\n\n"
                "1. npm 包与平台二进制的分发机制\n2. OAuth Device Flow 的改造点\n"
                "3. REST API 的 alias 作用域设计\n4. 两步确认机制\n\n"
                "大约 40 分钟，含现场演示。你看可以吗？\n\n— Demo"
            ),
            "body_format": "PLAIN",
            "created_at": int(NOW - 3 * DAY),
            "is_read": True,
            "attachments": [],
            "dir": "sent",
        },
        {
            "message_id": "msg_006",
            "from": {"name": "Agently Demo", "email": "agent@qq.com"},
            "to": [{"email": "team@tencent.com"}],
            "subject": "Re: 本周产品评审会议纪要",
            "snippet": "收到，路线图部分我补充一点关于安全边界的说明。",
            "body": (
                "> 各位好，\n>\n> 本周产品评审会议纪要如下：\n"
                "> 1. Q3 路线图 — 确认以「邮箱 Agent 化」为核心主线\n\n"
                "补充一点：安全边界需要单独列一项，尤其是 prompt 注入防护和 URL 同源校验。"
            ),
            "body_format": "PLAIN",
            "created_at": int(NOW - 4 * DAY),
            "is_read": True,
            "attachments": [],
            "dir": "sent",
        },
        {
            "message_id": "msg_007",
            "from": {"name": "订阅周刊", "email": "weekly@example.com"},
            "to": [{"email": "agent@qq.com"}],
            "subject": "前端周刊 #128 — 关于 Web Components 的再思考",
            "snippet": "本期话题：Shadow DOM 的边界、CSS 容器查询实战、以及一个 3KB 的状态管理库…",
            "body": (
                "## 前端周刊 #128\n\n本期精选：\n\n"
                "- **Shadow DOM 的边界在哪里？** — 一篇颇具争议的长文\n"
                "- **CSS 容器查询实战** — 从媒体查询迁移的完整指南\n"
                "- **3KB 的状态管理库** — 为什么小即是美\n\n"
                "> 退订请点击邮件底部链接。"
            ),
            "body_format": "MARKDOWN",
            "created_at": int(NOW - 5 * DAY),
            "is_read": True,
            "attachments": [],
            "dir": "inbox",
        },
        {
            "message_id": "msg_008",
            "from": {"name": "系统通知", "email": "system@tencent.com"},
            "to": [{"email": "agent@qq.com"}],
            "subject": "你的存储空间即将用满",
            "snippet": "当前使用率 92%。建议清理回收站或升级容量。",
            "body": (
                "你的邮箱存储空间使用率已达 **92%**。\n\n当前：18.4 GB / 20 GB\n\n"
                "建议操作：\n1. 清空回收站（可释放约 2.1 GB）\n2. 删除大附件邮件\n3. 升级至 100 GB 容量\n\n—— 系统通知"
            ),
            "body_format": "MARKDOWN",
            "created_at": int(NOW - 6 * DAY),
            "is_read": True,
            "attachments": [],
            "dir": "inbox",
        },
        {
            "message_id": "msg_009",
            "from": {"name": "推广", "email": "promo@example.com"},
            "to": [{"email": "agent@qq.com"}],
            "subject": "限时优惠 — 云服务器 1 折起",
            "snippet": "新用户专享，错过再等一年。",
            "body": "限时优惠！\n\n云服务器 1 折起，新用户专享。\n\n[立即抢购](https://example.com/promo)",
            "body_format": "MARKDOWN",
            "created_at": int(NOW - 7 * DAY),
            "is_read": True,
            "attachments": [],
            "dir": "inbox",
            "deleted": True,
        },
    ]


def _clone(m: dict[str, Any]) -> dict[str, Any]:
    import json

    return cast(dict[str, Any], json.loads(json.dumps(m)))


def _strip_tags(s: str) -> str:
    return re.sub(r"[#*`>|_\-]", " ", re.sub(r"<[^>]*>", " ", str(s or "")))


class DemoStore:
    """In-memory stand-in for AccountStore."""

    def __init__(self) -> None:
        self._accounts: dict[str, Any] = {}

    def list(self) -> builtins.list[dict[str, Any]]:
        return [
            {
                "id": k,
                "email": a.get("email", ""),
                "aliasId": a.get("aliasId", ""),
                "displayName": a.get("displayName") or a.get("email") or k,
                "addedAt": a.get("addedAt", 0),
            }
            for k, a in self._accounts.items()
        ]

    def get(self, account_id: str) -> dict[str, Any] | None:
        return self._accounts.get(account_id)

    def create_pending(self) -> str:
        acc_id = "acc_demo"
        self._accounts[acc_id] = {
            "addedAt": int(time.time() * 1000),
            "status": "pending",
            **DEMO_PROFILE,
        }
        return acc_id

    def complete_login(self, account_id: str, tokens: dict[str, Any]) -> dict[str, Any]:
        acc = self._accounts.setdefault(account_id, {})
        acc.update(tokens)
        acc["status"] = "active"
        acc.update({k: v for k, v in DEMO_PROFILE.items() if k != "profile"})
        return dict(acc)

    def fail_login(self, account_id: str, message: str) -> None:
        if account_id in self._accounts:
            self._accounts[account_id]["error"] = message

    def update_tokens(self, account_id: str, tokens: dict[str, Any]) -> None:
        self._accounts.setdefault(account_id, {}).update(tokens)

    def set_profile(self, account_id: str, profile: dict[str, Any]) -> None:
        acc = self._accounts.setdefault(account_id, {})
        acc["email"] = profile.get("email") or acc.get("email", "")
        acc["aliasId"] = profile.get("aliasId") or acc.get("aliasId", "")
        acc["displayName"] = profile.get("displayName") or acc.get("displayName", "")
        acc["profile"] = profile

    def remove(self, account_id: str) -> None:
        self._accounts.pop(account_id, None)

    # -- per-account state (delegated to the single demo api instance) ---- #
    def list_drafts(self, account_id: str) -> builtins.list[dict[str, Any]]:
        api = _ensure_singleton()
        return api.list_drafts()

    def get_draft(self, account_id: str, draft_id: str) -> dict[str, Any] | None:
        api = _ensure_singleton()
        return api.get_draft(draft_id)

    def upsert_draft(self, account_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        api = _ensure_singleton()
        return api.upsert_draft(draft)

    def delete_draft(self, account_id: str, draft_id: str) -> bool:
        api = _ensure_singleton()
        return api.delete_draft(draft_id)

    def get_signature(self, account_id: str) -> dict[str, Any]:
        api = _ensure_singleton()
        return api.get_signature()

    def set_signature(self, account_id: str, sig: dict[str, Any]) -> dict[str, Any]:
        api = _ensure_singleton()
        return api.set_signature(sig)

    def list_stars(self, account_id: str) -> builtins.list[str]:
        api = _ensure_singleton()
        return api.list_stars()

    def star(self, account_id: str, message_id: str) -> bool:
        api = _ensure_singleton()
        return api.star_message(message_id)

    def unstar(self, account_id: str, message_id: str) -> bool:
        api = _ensure_singleton()
        return api.unstar_message(message_id)

    def list_contacts(self, account_id: str) -> builtins.list[dict[str, Any]]:
        api = _ensure_singleton()
        return api.list_contacts()

    def add_contact(self, account_id: str, email: str, name: str = "") -> dict[str, Any]:
        api = _ensure_singleton()
        return api.add_contact(email, name)

    def remove_contact(self, account_id: str, email: str) -> bool:
        api = _ensure_singleton()
        return api.remove_contact(email)


class _NotFound(Exception):
    def __init__(self, what: str = "message not found") -> None:
        super().__init__(what)
        self.status = 404


# Module-level singleton — the server imports this once.
demo_api = None


def _ensure_singleton() -> DemoApi:
    global demo_api
    if demo_api is None:
        demo_api = DemoApi()
    return demo_api


class DemoApi:
    """Serves the seed mailbox. Mirrors AgentlyApi's surface."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = _seed()
        self._drafts: dict[str, dict[str, Any]] = {}
        self._stars: list[str] = [m["message_id"] for m in self.messages if m.get("starred")]
        self._contacts: dict[str, dict[str, Any]] = {
            "github@example.com": {
                "name": "GitHub",
                "email": "github@example.com",
                "addedAt": int(time.time() * 1000),
            },
            "team@tencent.com": {
                "name": "Tencent Team",
                "email": "team@tencent.com",
                "addedAt": int(time.time() * 1000),
            },
            "pm@tencent.com": {
                "name": "产品团队",
                "email": "pm@tencent.com",
                "addedAt": int(time.time() * 1000),
            },
        }
        self._signature: dict[str, str] = {
            "plain": "\n—\nAgent Demo\nagent@qq.com",
            "html": "<p>—<br>Agent Demo<br>agent@qq.com</p>",
        }
        self._next_id = 100

    # -- identity ---------------------------------------------------------- #
    def me(self) -> dict[str, Any]:
        return cast(dict[str, Any], dict(DEMO_PROFILE["profile"]))

    def aliases(self) -> dict[str, Any]:
        me = self.me()
        return {"aliases": me["aliases"], "default_alias_id": me["alias_id"]}

    # -- helpers ----------------------------------------------------------- #
    def _inbox(self) -> list[dict[str, Any]]:
        return [
            m
            for m in self.messages
            if not m.get("deleted") and (m.get("dir") or "inbox") == "inbox"
        ]

    def _sent(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if not m.get("deleted") and m.get("dir") == "sent"]

    def _trash(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("deleted")]

    def _page(self, rows: list[dict[str, Any]], limit: int, before: str | None) -> dict[str, Any]:
        if before:
            try:
                t = _parse_ts(before)
                rows = [m for m in rows if m.get("created_at", 0) < t]
            except Exception:
                pass
        return {
            "data": [self._decorate(m) for m in rows[:limit]],
            "pagination": {"next_cursor": None, "has_more": False},
            "rate_limits": {"messages_per_minute": 60, "remaining": 59},
            "constraints": {
                "max_attachment_count": 20,
                "max_total_attachments_size_bytes": 52_428_800,
            },
        }

    def _decorate(self, m: dict[str, Any]) -> dict[str, Any]:
        cloned = _clone(m)
        cloned["starred"] = cloned.get("message_id") in self._stars
        return cloned

    # -- messages ---------------------------------------------------------- #
    def list_messages(
        self,
        alias_id: str,
        *,
        limit: int = 25,
        before: str | None = None,
        is_read: bool | None = None,
        folder: str | None = None,
    ) -> dict[str, Any]:
        if folder == "trash":
            return {
                "data": [self._decorate(m) for m in self._trash()[:limit]],
                "pagination": {"next_cursor": None, "has_more": False},
            }
        if folder == "sent":
            return self._page(self._sent(), limit, before)
        if is_read is False:
            rows = [m for m in self._inbox() if m.get("is_read") is False]
            return self._page(rows, limit, before)
        return self._page(self._inbox(), limit, before)

    def get_message(self, alias_id: str, message_id: str) -> dict[str, Any]:
        m = next((x for x in self.messages if x["message_id"] == message_id), None)
        if not m:
            raise _NotFound()
        return {"message": self._decorate(m)}

    def search_messages(self, alias_id: str, q: str, *, scope: str | None = None) -> dict[str, Any]:
        needle = (q or "").lower()
        hits = [
            m
            for m in self.messages
            if not m.get("deleted")
            and (
                needle in m.get("subject", "").lower()
                or needle in _strip_tags(m.get("body", "")).lower()
            )
        ]
        return {
            "data": [self._decorate(m) for m in hits],
            "pagination": {"next_cursor": None, "has_more": False},
        }

    def _recipients(self, items: Any) -> list[str]:
        out = []
        for r in items or []:
            v = r.get("email") or r.get("name") if isinstance(r, dict) else r
            if v:
                out.append(v)
        return out

    def send_message(self, alias_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        to = self._recipients(payload.get("to_recipients"))
        if not to:
            raise ApiErrorLike(400, "at least one recipient is required")
        if not payload.get("confirmation_token"):
            return {
                "confirmation_required": True,
                "confirmation_token": "demo_ct_"
                + re.sub(r"[^a-z0-9]", "", str(abs(hash(str(payload))))[:9]),
            }
        self._next_id += 1
        msg = {
            "message_id": f"msg_{self._next_id}",
            "from": {"name": "Agently Demo", "email": "agent@qq.com"},
            "to": [{"email": e} for e in to],
            "cc": [{"email": e} for e in self._recipients(payload.get("cc_recipients"))],
            "subject": payload.get("subject") or "(无主题)",
            "snippet": str(payload.get("body") or "")[:120],
            "body": payload.get("body") or "",
            "body_format": payload.get("body_format") or "PLAIN",
            "created_at": int(time.time() * 1000),
            "is_read": True,
            "attachments": [
                {
                    "attachment_id": f"att_new_{i}",
                    "filename": f"attachment-{i + 1}",
                    "size": 1024 * (i + 3),
                    "content_type": "application/octet-stream",
                }
                for i, _ in enumerate(payload.get("contentfile_id") or [])
            ],
            "dir": "sent",
            "queued": True,
            "starred": False,
        }
        self.messages.insert(0, msg)
        return {"message": _clone(msg), "queued": True}

    def reply_message(
        self, alias_id: str, message_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.send_message(alias_id, payload)

    def forward_message(
        self, alias_id: str, message_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.send_message(alias_id, payload)

    def trash_message(self, alias_id: str, message_id: str) -> dict[str, Any]:
        m = next((x for x in self.messages if x["message_id"] == message_id), None)
        if not m:
            raise _NotFound()
        m["deleted"] = True
        if message_id in self._stars:
            self._stars.remove(message_id)
        return {"trashed": True, "message_id": message_id}

    def delete_message(self, alias_id: str, message_id: str) -> dict[str, Any]:
        before = len(self.messages)
        self.messages = [m for m in self.messages if m["message_id"] != message_id]
        self._stars = [s for s in self._stars if s != message_id]
        if len(self.messages) == before:
            raise _NotFound()
        return {"deleted_count": 1, "message_id": message_id}

    def empty_trash(self, alias_id: str) -> dict[str, Any]:
        n = len(self._trash())
        self.messages = [m for m in self.messages if not m.get("deleted")]
        return {"deleted_count": n}

    def upload_file(
        self, alias_id: str, data: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        import secrets

        return {
            "contentfile_id": "cf_" + secrets.token_hex(5),
            "filename": filename,
            "size": len(data),
            "content_type": content_type or "application/octet-stream",
        }

    def download_attachment(
        self, alias_id: str, message_id: str, attachment_id: str
    ) -> dict[str, Any]:
        m = next((x for x in self.messages if x["message_id"] == message_id), None)
        a = next(
            (
                x
                for x in (m or {}).get("attachments", [])
                if x.get("attachment_id") == attachment_id
            ),
            None,
        )
        if not a:
            raise _NotFound("attachment not found")
        import base64

        content = (
            f"Demo attachment\n\nmessage: {message_id}\nattachment: {attachment_id}\n"
            f"filename: {a.get('filename')}\n"
        )
        return {
            "url": "data:text/plain;base64," + base64.b64encode(content.encode()).decode(),
            "filename": a.get("filename"),
        }

    def watch_events(self, alias_id: str, *, timeout: int = 60) -> dict[str, Any]:
        return {"events": [], "occurred_at": _iso_now()}

    # -- stars / signature / contacts (mirror store API) ------------------ #
    def list_stars(self) -> list[str]:
        return sorted(self._stars)

    def star_message(self, message_id: str) -> bool:
        if message_id in self._stars:
            return False
        self._stars.append(message_id)
        return True

    def unstar_message(self, message_id: str) -> bool:
        if message_id not in self._stars:
            return False
        self._stars.remove(message_id)
        return True

    def list_drafts(self) -> list[dict[str, Any]]:
        return sorted(self._drafts.values(), key=lambda d: d.get("updatedAt", 0), reverse=True)

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        return self._drafts.get(draft_id)

    def upsert_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        import secrets

        if not draft.get("draftId"):
            draft["draftId"] = "drf_" + secrets.token_hex(6)
        draft["updatedAt"] = int(time.time() * 1000)
        self._drafts[draft["draftId"]] = dict(draft)
        return draft

    def delete_draft(self, draft_id: str) -> bool:
        return self._drafts.pop(draft_id, None) is not None

    def get_signature(self) -> dict[str, Any]:
        return dict(self._signature)

    def set_signature(self, sig: dict[str, Any]) -> dict[str, Any]:
        self._signature = {"plain": str(sig.get("plain", "")), "html": str(sig.get("html", ""))}
        return dict(self._signature)

    def list_contacts(self) -> list[dict[str, Any]]:
        return sorted(
            [
                {"name": c["name"], "email": e, "addedAt": c["addedAt"]}
                for e, c in self._contacts.items()
            ],
            key=lambda c: c["email"],
        )

    def add_contact(self, email: str, name: str = "") -> dict[str, Any]:
        email = email.strip().lower()
        if not email:
            raise ApiErrorLike(400, "email required")
        existing = self._contacts.get(email, {})
        contact = {
            "name": name or existing.get("name", ""),
            "email": email,
            "addedAt": existing.get("addedAt", int(time.time() * 1000)),
        }
        self._contacts[email] = contact
        return contact

    def remove_contact(self, email: str) -> bool:
        email = email.strip().lower()
        return self._contacts.pop(email, None) is not None


class ApiErrorLike(Exception):
    """Local error carrying an HTTP status, used by the demo API."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = ""
        self.request_id = ""
        self.hints = None


def _parse_ts(v: Any) -> float:
    if isinstance(v, int | float):
        return float(v) if v < 1e12 else float(v)
    from datetime import datetime

    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
