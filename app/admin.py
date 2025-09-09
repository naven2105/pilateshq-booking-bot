# app/admin.py
from __future__ import annotations

import logging
import re
from typing import Optional

from .utils import send_whatsapp_text
from . import crud

ADMIN_HELP = (
    "🛠 *Admin Menu*\n"
    "• inbox — list latest items\n"
    "• inbox unread — only unread\n"
    "• inbox action — needs action\n"
    "• inbox open — open items\n"
    "• inbox #123 — view item 123\n"
    "• read 123 | unread 123 | resolve 123\n"
    "• hourly — show current upcoming\n"
    "• recap — show today (full day)\n"
    "• today — show today (upcoming)\n"
    "• view clients — quick list\n"
    "• accept 123 name=Jane Doe — approve a lead (from inbox item #)\n"
    "• decline 123 — close a lead item\n"
)

def _fmt_inbox_list(rows: list[dict]) -> str:
    if not rows:
        return "📥 Inbox is empty."
    out = []
    for r in rows[:10]:
        badge = []
        if r.get("is_unread"): badge.append("unread")
        if r.get("action_required"): badge.append("action")
        if r.get("status") and r["status"] != "open": badge.append(r["status"])
        tags = f" ({', '.join(badge)})" if badge else ""
        out.append(f"#{r['id']} — {r['kind']} — {r['title']}{tags}")
    out.append("\nTry: *inbox unread*, *inbox action*, *inbox open*, or *inbox #123*")
    return "\n".join(out)

def _fmt_inbox_item(r: dict) -> str:
    badge = []
    if r.get("is_unread"): badge.append("unread")
    if r.get("action_required"): badge.append("action")
    if r.get("status") and r["status"] != "open": badge.append(r["status"])
    tag = f" ({', '.join(badge)})" if badge else ""
    lines = [
        f"📄 *Inbox item #{r['id']}*{tag}",
        f"*Kind:* {r['kind']}",
        f"*Title:* {r['title']}",
        f"*Body:*\n{r['body']}",
    ]
    if r.get("source"): lines.append(f"*Source:* {r['source']}")
    if r.get("created_at"): lines.append(f"*Created:* {r['created_at']}")
    lines.append("\nActions: read 123 | unread 123 | resolve 123")
    return "\n".join(lines)

def _admin_inbox_command(wa: str, text: str) -> bool:
    t = (text or "").strip().lower()

    # Top-level lists
    if t in {"inbox", "inbox list"}:
        cnt = crud.inbox_counts()
        rows = crud.inbox_list(limit=10)
        header = (
            f"📥 *Inbox*\n"
            f"open:{cnt['open_cnt']} • unread:{cnt['unread_cnt']} • action:{cnt['action_cnt']} • total:{cnt['total_cnt']}\n"
        )
        send_whatsapp_text(wa, header + _fmt_inbox_list(rows))
        return True

    if t == "inbox unread":
        rows = crud.inbox_list(unread_only=True, limit=10)
        send_whatsapp_text(wa, _fmt_inbox_list(rows))
        return True

    if t == "inbox action":
        rows = crud.inbox_list(action_required=True, limit=10)
        send_whatsapp_text(wa, _fmt_inbox_list(rows))
        return True

    if t == "inbox open":
        rows = crud.inbox_list(status="open", limit=10)
        send_whatsapp_text(wa, _fmt_inbox_list(rows))
        return True

    # View a single item
    m = re.match(r"inbox\s*#?(\d+)\s*$", t)
    if m:
        iid = int(m.group(1))
        detail = crud.inbox_get(iid)
        if not detail:
            send_whatsapp_text(wa, f"Item #{iid} not found.")
        else:
            send_whatsapp_text(wa, _fmt_inbox_item(detail))
        return True

    # Update flags
    m = re.match(r"(read|unread|resolve)\s+(\d+)", t)
    if m:
        cmd, sid = m.group(1), int(m.group(2))
        if cmd == "read":
            crud.inbox_mark_read(sid)
            send_whatsapp_text(wa, f"Marked #{sid} as read.")
        elif cmd == "unread":
            crud.inbox_mark_unread(sid)
            send_whatsapp_text(wa, f"Marked #{sid} as unread.")
        else:
            crud.inbox_resolve(sid)
            send_whatsapp_text(wa, f"Resolved #{sid}.")
        return True

    # Lead acceptance / decline from inbox item
    m = re.match(r"accept\s+(\d+)\s+name=(.+)$", t)
    if m:
        iid = int(m.group(1))
        name = m.group(2).strip()
        ok, msg = crud.lead_accept_from_inbox(iid, name)
        send_whatsapp_text(wa, msg)
        return True

    m = re.match(r"decline\s+(\d+)\s*$", t)
    if m:
        iid = int(m.group(1))
        ok, msg = crud.lead_decline_from_inbox(iid)
        send_whatsapp_text(wa, msg)
        return True

    return False

def _admin_other_commands(wa: str, text: str) -> bool:
    """
    Slots for your existing admin functions (hourly/today/recap/view clients etc.)
    Return True if handled, else False → we'll show help.
    """
    t = (text or "").strip().lower()
    if t == "hourly":
        # delegate to your existing /tasks endpoint or local function if present
        send_whatsapp_text(wa, "Requesting hourly… (tip: you can also use curl /tasks/admin-notify)")
        return True
    if t == "recap":
        send_whatsapp_text(wa, "Requesting 20:00 recap…")
        return True
    if t == "today":
        send_whatsapp_text(wa, "Requesting today (upcoming)…")
        return True
    if t == "view clients":
        # Minimal quick list; you can expand to a paginated picker
        rows = crud.list_clients(limit=10, offset=0)
        if not rows:
            send_whatsapp_text(wa, "No clients found.")
            return True
        lines = ["👥 *Clients (top 10)*"]
        for r in rows:
            nm = (r.get("name") or "(no name)").strip()
            wa_num = r.get("wa_number") or ""
            lines.append(f"• {nm} — {wa_num}")
        send_whatsapp_text(wa, "\n".join(lines))
        return True
    return False

def handle_admin_action(wa: str, reply_id: str | None, body: str | None = None):
    """
    Main admin entry. We ALWAYS finish by showing the admin menu so the
    available commands are discoverable.
    """
    text = (body or "").strip()
    try:
        # 1) Inbox commands first
        if _admin_inbox_command(wa, text):
            send_whatsapp_text(wa, ADMIN_HELP)
            return
        # 2) Other admin commands (hourly/today/recap/etc.)
        if _admin_other_commands(wa, text):
            send_whatsapp_text(wa, ADMIN_HELP)
            return
        # 3) Anything else → show help
        send_whatsapp_text(wa, "💬 Admin here. What would you like to do?\n\n" + ADMIN_HELP)
    except Exception:
        logging.exception("admin handler failed")
        send_whatsapp_text(wa, "Admin command failed.\n\n" + ADMIN_HELP)
