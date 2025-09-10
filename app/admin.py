# app/admin.py
from __future__ import annotations

import logging
from typing import Optional

from .utils import send_whatsapp_text, send_whatsapp_buttons
from .config import TZ_NAME
from . import crud


# ─────────────────────────────────────────────────────────────────────────────
# Button Menus
# ─────────────────────────────────────────────────────────────────────────────

def _admin_home_buttons():
    # WhatsApp Cloud API supports up to 3 buttons per message; we’ll group.
    return [
        {"id": "btn_inbox", "title": "Inbox"},
        {"id": "btn_clients", "title": "Clients"},
        {"id": "btn_sessions", "title": "Sessions"},
    ], [
        {"id": "btn_hourly", "title": "Hourly"},
        {"id": "btn_recap", "title": "Recap"},
        {"id": "btn_help", "title": "Help"},
    ]


def _send_home(wa: str):
    rows1, rows2 = _admin_home_buttons()
    send_whatsapp_buttons(
        wa,
        text=(
            "👩‍💼 *Admin*\n"
            "Pick an option below. You can also type: *inbox*, *clients*, *sessions*, *hourly*, *recap*, or *search nadia*."
        ),
        buttons=rows1
    )
    # second row
    send_whatsapp_buttons(
        wa,
        text="More:",
        buttons=rows2
    )


# ─────────────────────────────────────────────────────────────────────────────
# Feature: Inbox quick views
# ─────────────────────────────────────────────────────────────────────────────

def _show_inbox_summary(wa: str):
    counts = crud.inbox_counts()
    recent = crud.inbox_recent(limit=5)
    lines = []
    for r in recent:
        badge = "🟡" if r.get("is_unread") else "⚪"
        need = " [action]" if r.get("action_required") else ""
        lines.append(f"• {badge} {r['kind']}: {r['title']}{need}")

    msg = (
        f"📥 *Inbox*\n"
        f"Unread: {counts.get('unread_count',0)}  |  Open: {counts.get('open_count',0)}  |  Action: {counts.get('action_count',0)}\n"
        + ("\n".join(lines) if lines else "— no recent items —")
    )
    send_whatsapp_text(wa, msg)


def _show_hourly(wa: str):
    rows = crud.inbox_recent(kind="hourly", limit=1)
    if rows:
        r = rows[0]
        send_whatsapp_text(wa, f"⏱ *Last hourly*\n{r['body']}")
    else:
        send_whatsapp_text(wa, "No hourly item found today.")
    _send_home(wa)


def _show_recap(wa: str):
    rows = crud.inbox_recent(kind="recap", limit=1)
    if rows:
        r = rows[0]
        send_whatsapp_text(wa, f"🧾 *Last recap*\n{r['body']}")
    else:
        send_whatsapp_text(wa, "No recap yet.")
    _send_home(wa)


# ─────────────────────────────────────────────────────────────────────────────
# Feature: Clients (search / quick view)
# ─────────────────────────────────────────────────────────────────────────────

def _format_client_card(c: dict) -> str:
    return f"*{c.get('name') or '(no name)'}*  —  {c.get('wa_number','')}\nID: {c['id']}"

def _show_client_card(wa: str, client: dict):
    # Upcoming + recent for context
    upcoming = crud.client_upcoming_bookings(client["id"], TZ_NAME)
    recent = crud.client_recent_history(client["id"], limit=5)

    lines = [f"👤 { _format_client_card(client) }"]
    if upcoming:
        lines.append("\n*Upcoming*:")
        for r in upcoming[:5]:
            lines.append(f"• {r['session_date']} {str(r['start_time'])[:5]} — {r['status']}")
    else:
        lines.append("\n*Upcoming*: —")

    if recent:
        lines.append("\n*Recent*:")
        for r in recent:
            lines.append(f"• {r['session_date']} {str(r['start_time'])[:5]} — {r['status']}")
    else:
        lines.append("\n*Recent*: —")

    send_whatsapp_text(wa, "\n".join(lines))
    _send_home(wa)


def _clients_entry(wa: str):
    # Show top 10 alphabetically + hint to search
    rows = crud.list_clients(limit=10, offset=0)
    if not rows:
        send_whatsapp_text(wa, "No clients found yet.\nTip: reply *search <name>* to find someone.")
        _send_home(wa)
        return
    lines = ["👥 *Clients* (first 10)"]
    for c in rows:
        lines.append(f"• {c['id']}: {c.get('name') or '(no name)'} — {c.get('wa_number','')}")
    lines.append("\nReply *search <name/phone/id>* to filter.")
    send_whatsapp_text(wa, "\n".join(lines))
    _send_home(wa)


def _search_clients(wa: str, q: str):
    try:
        result = crud.find_one_client(q)
    except Exception:
        logging.exception("find_one_client failed")
        send_whatsapp_text(wa, "⚠️ Sorry, I couldn’t search clients just now.")
        _send_home(wa)
        return

    if result is None:
        send_whatsapp_text(wa, f"🙈 No client found for “{q}”. Try a few more letters.")
        _send_home(wa)
        return

    # Multi → show list
    if isinstance(result, dict) and "_multi" in result:
        picks = result["_multi"]
        lines = ["Found multiple matches:"]
        for c in picks:
            lines.append(f"• {c['id']}: {c.get('name') or '(no name)'} — {c.get('wa_number','')}")
        lines.append("\nReply with the *ID* to open the client card.")
        send_whatsapp_text(wa, "\n".join(lines))
        return

    # Single
    _show_client_card(wa, result)


# ─────────────────────────────────────────────────────────────────────────────
# Feature: Sessions (today)
# ─────────────────────────────────────────────────────────────────────────────

def _sessions_today(wa: str, upcoming_only: bool = True):
    rows = crud.sessions_today_with_names(TZ_NAME, upcoming_only=upcoming_only)
    if not rows:
        send_whatsapp_text(wa, "🗓 Today: — none —")
        _send_home(wa)
        return
    out = ["🗓 *Today’s sessions* (upcoming)" if upcoming_only else "🗓 *Today’s sessions* (full day)"]
    for r in rows:
        names = (r.get("names") or "").strip()
        status = str(r.get("status") or "").lower()
        badge = "🔒 full" if status == "full" or (r.get("booked_count", 0) >= r.get("capacity", 0)) else "✅ open"
        names_part = " (no bookings)" if not names else f" — {names}"
        out.append(f"• {str(r['start_time'])[:5]}{names_part}  ({badge})")
    send_whatsapp_text(wa, "\n".join(out))
    _send_home(wa)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point from router
# ─────────────────────────────────────────────────────────────────────────────

def handle_admin_action(wa: str, reply_id: Optional[str] = None, body: Optional[str] = None):
    """
    Stateless handler. Admin can type or tap buttons.
    Recognized:
      - inbox / hourly / recap
      - clients / sessions
      - search <term> (name/phone/id)
      - numeric ID alone => open that client card
      - greetings/admin/menu/help => home
    """
    try:
        t = (body or "").strip()
        tl = t.lower()

        # Button replies land as exact titles; interactive payloads may differ.
        if tl in {"", "hi", "hello", "admin", "menu", "help"}:
            _send_home(wa)
            return

        if tl in {"inbox", "btn_inbox"}:
            _show_inbox_summary(wa)
            _send_home(wa)
            return

        if tl in {"hourly", "btn_hourly"}:
            _show_hourly(wa)
            return

        if tl in {"recap", "btn_recap"}:
            _show_recap(wa)
            return

        if tl in {"clients", "btn_clients"}:
            _clients_entry(wa)
            return

        if tl in {"sessions", "btn_sessions"}:
            _sessions_today(wa, upcoming_only=True)
            return

        if tl.startswith("search "):
            q = t.split(" ", 1)[1]
            _search_clients(wa, q)
            return

        # If the admin just replies with a number, treat it as client ID
        if tl.isdigit():
            result = crud.find_one_client(tl)
            if result and not (isinstance(result, dict) and "_multi" in result):
                _show_client_card(wa, result)
                return
            # else fall through to help

        # Unknown → show help
        send_whatsapp_text(wa, "Unknown admin message. Try: *inbox*, *clients*, *sessions*, *hourly*, *recap*, or *search <name>*.")
        _send_home(wa)

    except Exception:
        logging.exception("handle_admin_action failed")
        send_whatsapp_text(wa, "⚠️ Admin action failed. Please try again.")
