# app/admin.py
from __future__ import annotations

import logging
from typing import Optional, List, Dict

from .utils import (
    send_whatsapp_text,
    send_whatsapp_buttons,
    normalize_wa,
)
from .config import TZ_NAME
from .crud import (
    inbox_counts,
    sessions_today_with_names,
    sessions_next_hour_with_names,
    list_clients,
)

# ──────────────────────────────────────────────────────────────────────────────
# Button payload IDs (keep short, stable)
# ──────────────────────────────────────────────────────────────────────────────
BTN_MAIN_INBOX     = "ADMIN_INBOX"
BTN_MAIN_CLIENTS   = "ADMIN_CLIENTS"
BTN_MAIN_SESSIONS  = "ADMIN_SESSIONS"

BTN_INBOX_OPEN     = "INBOX_OPEN"
BTN_INBOX_MARKREAD = "INBOX_MARKREAD"
BTN_BACK_HOME      = "BACK_HOME"

BTN_CLIENTS_LIST   = "CLIENTS_LIST"
BTN_CLIENTS_SEARCH = "CLIENTS_SEARCH"   # (future)
BTN_CLIENTS_BACK   = BTN_BACK_HOME

BTN_SES_HOURLY     = "SES_HOURLY"
BTN_SES_TODAY      = "SES_TODAY"
BTN_SES_RECAP      = "SES_RECAP"
BTN_SES_BACK       = BTN_BACK_HOME


# ──────────────────────────────────────────────────────────────────────────────
# Menus
# ──────────────────────────────────────────────────────────────────────────────
def _format_badges() -> str:
    counts = inbox_counts()
    unread = counts.get("unread", 0)
    act    = counts.get("action_required", 0)
    parts: List[str] = []
    if unread:
        parts.append(f"🔔 Unread: {unread}")
    if act:
        parts.append(f"❗ Action: {act}")
    return ("  •  " + "  |  ".join(parts)) if parts else ""


def show_admin_home(wa: str) -> None:
    """Main admin menu with 3 buttons."""
    title = "🛠️ Admin menu" + _format_badges()
    # At most 3 reply buttons
    buttons = [
        {"id": BTN_MAIN_INBOX,    "title": "Inbox"},
        {"id": BTN_MAIN_CLIENTS,  "title": "Clients"},
        {"id": BTN_MAIN_SESSIONS, "title": "Sessions"},
    ]
    send_whatsapp_buttons(wa, title, buttons)


def show_inbox_menu(wa: str) -> None:
    title = "🗂 Inbox"
    buttons = [
        {"id": BTN_INBOX_OPEN,     "title": "Open items"},
        {"id": BTN_INBOX_MARKREAD, "title": "Mark all read"},
        {"id": BTN_BACK_HOME,      "title": "Back"},
    ]
    send_whatsapp_buttons(wa, title, buttons)


def show_clients_menu(wa: str) -> None:
    title = "👥 Clients"
    buttons = [
        {"id": BTN_CLIENTS_LIST,  "title": "List 10"},
        {"id": BTN_CLIENTS_SEARCH,"title": "Search (soon)"},
        {"id": BTN_CLIENTS_BACK,  "title": "Back"},
    ]
    send_whatsapp_buttons(wa, title, buttons)


def show_sessions_menu(wa: str) -> None:
    title = "🗓 Sessions"
    buttons = [
        {"id": BTN_SES_HOURLY, "title": "Hourly now"},
        {"id": BTN_SES_TODAY,  "title": "Today (names)"},
        {"id": BTN_SES_RECAP,  "title": "20:00 recap"},
    ]
    send_whatsapp_buttons(wa, title, buttons)


# ──────────────────────────────────────────────────────────────────────────────
# Content builders
# ──────────────────────────────────────────────────────────────────────────────
def _fmt_rows(rows: List[Dict]) -> str:
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        start = str(r["start_time"])[:5]
        names = (r.get("names") or "").strip()
        if names:
            out.append(f"• {start} – {names}  ({'🔒 full' if str(r['status']).lower()=='full' else '✅ open'})")
        else:
            out.append(f"• {start} – (no bookings)  ({'🔒 full' if str(r['status']).lower()=='full' else '✅ open'})")
    return "\n".join(out)


def _send_hourly_now(wa: str) -> None:
    nxt = sessions_next_hour_with_names(TZ_NAME)
    if nxt:
        body = "🕒 Next hour:\n" + _fmt_rows(nxt)
    else:
        body = "🕒 Next hour: no upcoming session."
    send_whatsapp_text(wa, body)
    # Return to menu for discoverability
    show_sessions_menu(wa)


def _send_today_names(wa: str) -> None:
    rows = sessions_today_with_names(TZ_NAME, upcoming_only=True)
    header = "🗓 Today’s sessions (upcoming)"
    body = f"{header}\n{_fmt_rows(rows)}"
    send_whatsapp_text(wa, body)
    show_sessions_menu(wa)


def _send_recap(wa: str) -> None:
    rows = sessions_today_with_names(TZ_NAME, upcoming_only=False)
    header = "🗓 Today’s sessions (full day)"
    body = f"{header}\n{_fmt_rows(rows)}"
    send_whatsapp_text(wa, body)
    show_sessions_menu(wa)


def _send_inbox_open(wa: str) -> None:
    # Minimal placeholder list (extend later with real SELECT)
    counts = inbox_counts()
    unread = counts.get("unread", 0)
    act    = counts.get("action_required", 0)
    send_whatsapp_text(wa, f"🗂 Inbox\nUnread: {unread}\nAction required: {act}\n\n(Full list view coming next.)")
    show_inbox_menu(wa)


def _mark_all_read(wa: str) -> None:
    # Minimal placeholder; implement a real UPDATE when you’re ready.
    send_whatsapp_text(wa, "✅ Marked all as read. (Note: wire the UPDATE when ready.)")
    show_inbox_menu(wa)


def _send_clients_list(wa: str) -> None:
    rows = list_clients(limit=10, offset=0)
    if not rows:
        send_whatsapp_text(wa, "No clients found.")
        show_clients_menu(wa)
        return
    lines = []
    for r in rows:
        nm = (r.get("name") or "").strip() or "(no name)"
        wn = r.get("wa_number") or ""
        lines.append(f"• {nm} – {wn}")
    send_whatsapp_text(wa, "👥 Clients (first 10):\n" + "\n".join(lines))
    show_clients_menu(wa)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point from router
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(
    wa: str,
    reply_id: Optional[str] = None,
    body: Optional[str] = None,
    btn_id: Optional[str] = None,
) -> None:
    """
    Unified admin dispatcher.
    - Prioritises button payload id (btn_id) if present.
    - Falls back to simple text commands: inbox, clients, sessions, hourly, recap, help.
    - Always returns the user to a button menu after an action.
    """
    wa = normalize_wa(wa)
    cmd = (body or "").strip().lower()

    # 1) Button-first routing
    if btn_id:
        if btn_id == BTN_MAIN_INBOX:    return show_inbox_menu(wa)
        if btn_id == BTN_MAIN_CLIENTS:  return show_clients_menu(wa)
        if btn_id == BTN_MAIN_SESSIONS: return show_sessions_menu(wa)

        if btn_id == BTN_INBOX_OPEN:     return _send_inbox_open(wa)
        if btn_id == BTN_INBOX_MARKREAD: return _mark_all_read(wa)
        if btn_id == BTN_BACK_HOME:      return show_admin_home(wa)

        if btn_id == BTN_CLIENTS_LIST:   return _send_clients_list(wa)
        if btn_id == BTN_CLIENTS_SEARCH: return send_whatsapp_text(wa, "🔎 Search coming soon…") or show_clients_menu(wa)

        if btn_id == BTN_SES_HOURLY: return _send_hourly_now(wa)
        if btn_id == BTN_SES_TODAY:  return _send_today_names(wa)
        if btn_id == BTN_SES_RECAP:  return _send_recap(wa)

    # 2) Text fallback routing
    if cmd in {"admin", "menu", "help"}:
        return show_admin_home(wa)

    if cmd in {"inbox"}:
        return show_inbox_menu(wa)

    if cmd in {"clients", "client"}:
        return show_clients_menu(wa)

    if cmd in {"sessions", "session"}:
        return show_sessions_menu(wa)

    if cmd in {"hourly"}:
        return _send_hourly_now(wa)

    if cmd in {"today", "names", "upcoming"}:
        return _send_today_names(wa)

    if cmd in {"recap", "20:00", "2000", "tonight"}:
        return _send_recap(wa)

    # Unknown → show home
    send_whatsapp_text(wa, "I didn’t recognise that. Here’s the admin menu:")
    show_admin_home(wa)
