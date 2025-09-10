# app/admin.py
from __future__ import annotations

import logging
from typing import Optional

from .utils import send_whatsapp_text, send_whatsapp_buttons, normalize_wa
from . import crud

# ──────────────────────────────────────────────────────────────────────────────
# Button payloads (ids). Keep them short and stable.
# ──────────────────────────────────────────────────────────────────────────────
BTN_INBOX     = "adm_inbox"
BTN_CLIENTS   = "adm_clients"
BTN_SESSIONS  = "adm_sessions"
BTN_HELP      = "adm_help"
BTN_BACK_HOME = "adm_home"

# ──────────────────────────────────────────────────────────────────────────────
# Home / Menu
# ──────────────────────────────────────────────────────────────────────────────

def _home_text() -> str:
    return (
        "🛠️ *Admin*\n"
        "Choose an option below."
    )

def _home_buttons():
    # WhatsApp Cloud API allows up to 3 buttons per message; we keep it compact.
    return [
        {"type": "reply", "reply": {"id": BTN_INBOX,    "title": "Inbox"}},
        {"type": "reply", "reply": {"id": BTN_CLIENTS,  "title": "Clients"}},
        {"type": "reply", "reply": {"id": BTN_SESSIONS, "title": "Sessions"}},
    ]

def _send_home(wa: str) -> None:
    # IMPORTANT: call utils with positional args (to, body, buttons)
    send_whatsapp_buttons(
        normalize_wa(wa),
        _home_text(),
        _home_buttons(),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Simple handlers for top-level sections
# ──────────────────────────────────────────────────────────────────────────────

def _handle_inbox(wa: str) -> None:
    """
    Show quick summary of inbox: unread/action counts, plus a short tip.
    """
    try:
        counts = crud.inbox_counts()  # returns dict like {"unread": X, "open": Y, "action": Z}
    except Exception:
        logging.exception("inbox_counts failed")
        counts = {"unread": 0, "open": 0, "action": 0}

    lines = [
        "📥 *Inbox*",
        f"• Unread: {counts.get('unread', 0)}",
        f"• Open: {counts.get('open', 0)}",
        f"• Action required: {counts.get('action', 0)}",
        "",
        "Type *inbox 5* to see last 5, or *inbox* to see default.",
    ]
    send_whatsapp_text(normalize_wa(wa), "\n".join(lines))
    _send_home(wa)

def _handle_clients(wa: str, body: str) -> None:
    """
    If admin typed e.g. 'clients nad', show first matches by name prefix.
    Otherwise, show a hint.
    """
    parts = (body or "").strip().split(maxsplit=1)
    q = parts[1] if len(parts) > 1 else ""

    if q:
        try:
            rows = crud.find_clients_by_prefix(q, limit=10)
        except Exception:
            logging.exception("find_clients_by_prefix failed")
            rows = []
        if not rows:
            send_whatsapp_text(normalize_wa(wa), f"🔎 No clients found for *{q}*.")
        else:
            out = ["👥 *Clients*"]
            for r in rows:
                nm = (r.get("name") or "").strip() or "(no name)"
                wa_num = r.get("wa_number") or ""
                cred = r.get("credits", 0)
                out.append(f"• {nm} — {wa_num} (credits: {cred})")
            send_whatsapp_text(normalize_wa(wa), "\n".join(out))
    else:
        send_whatsapp_text(
            normalize_wa(wa),
            "👥 *Clients*\nType: *clients <prefix>* (e.g., *clients nad*)"
        )
    _send_home(wa)

def _handle_sessions(wa: str) -> None:
    """
    Very lightweight teaser – the hourlies/recaps already push detail.
    """
    try:
        today = crud.sessions_today_names()
    except Exception:
        logging.exception("sessions_today_names failed")
        today = []

    if not today:
        send_whatsapp_text(normalize_wa(wa), "🗓 No sessions found for today.")
        _send_home(wa)
        return

    # Compact list
    lines = ["🗓 *Today (names)*"]
    for r in today:
        hhmm = str(r["start_time"])[:5]
        names = (r.get("names") or "").strip() or "(no bookings)"
        status = "🔒 full" if (r["booked_count"] >= r["capacity"]) else "✅ open"
        lines.append(f"• {hhmm} — {names} ({status})")

    send_whatsapp_text(normalize_wa(wa), "\n".join(lines))
    _send_home(wa)

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def handle_admin_action(wa: str,
                        reply_id: Optional[str] = None,
                        body: str = "",
                        btn_id: Optional[str] = None) -> None:
    """
    Accepts 3-arg or 4-arg calls. `btn_id` is optional.
    Any admin input should end by showing the Admin home menu again.
    """
    try:
        # Button wins when present
        if btn_id:
            if btn_id == BTN_INBOX:
                _handle_inbox(wa)
                return
            if btn_id == BTN_CLIENTS:
                _handle_clients(wa, body or "")
                return
            if btn_id == BTN_SESSIONS:
                _handle_sessions(wa)
                return
            if btn_id == BTN_BACK_HOME or btn_id == BTN_HELP:
                _send_home(wa)
                return
            # Unknown button → just home
            _send_home(wa)
            return

        # No button: parse free text, but always fall back to home.
        t = (body or "").strip().lower()

        if t.startswith("inbox"):
            _handle_inbox(wa)
            return

        if t.startswith("clients"):
            _handle_clients(wa, body or "")
            return

        if t.startswith("sessions") or t in {"today", "schedule"}:
            _handle_sessions(wa)
            return

        if t in {"admin", "hi", "hello", "help", "menu"}:
            _send_home(wa)
            return

        # Default: show home so admin always sees options
        _send_home(wa)

    except Exception:
        logging.exception("handle_admin_action failed")
        # Ensure we don’t leave admin stranded
        try:
            send_whatsapp_text(normalize_wa(wa), "⚠ Admin action failed. Please try again.")
        finally:
            _send_home(wa)
