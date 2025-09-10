# app/admin.py
from __future__ import annotations

import logging
from typing import Optional, List

from .utils import send_whatsapp_text, send_whatsapp_buttons, normalize_wa
from .config import NADINE_WA
from .admin_nlp import parse_admin_command, parse_admin_client_command

# ──────────────────────────────────────────────────────────────────────────────
# Button IDs (stable)
# ──────────────────────────────────────────────────────────────────────────────
BTN_INBOX    = "adm_inbox"
BTN_CLIENTS  = "adm_clients"
BTN_SESSIONS = "adm_sessions"
BTN_BACK     = "adm_back"

# ──────────────────────────────────────────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────────────────────────────────────────
def _admin_home_text() -> str:
    return "🛠 Admin\nChoose an option below.."

def _admin_home_buttons() -> List[str]:
    return [
        {"title": "Inbox",   "id": BTN_INBOX},
        {"title": "Clients", "id": BTN_CLIENTS},
        {"title": "Sessions","id": BTN_SESSIONS},
    ]

def _send_home(wa: str) -> None:
    try:
        send_whatsapp_buttons(
            wa,
            _admin_home_text(),
            _admin_home_buttons(),
        )
    except Exception:
        logging.exception("failed to send admin home buttons; falling back to text")
        send_whatsapp_text(wa, _admin_home_text() + "\n• Inbox\n• Clients\n• Sessions")

# ──────────────────────────────────────────────────────────────────────────────
# Section stubs (expand later)
# ──────────────────────────────────────────────────────────────────────────────
def _open_inbox(wa: str) -> None:
    send_whatsapp_text(wa, "📥 *Inbox*\n(Coming soon: unread/action required counts and quick actions.)")
    _send_home(wa)

def _open_clients(wa: str) -> None:
    send_whatsapp_text(wa, "👤 *Clients*\nType the first 3+ letters to search (e.g., *nad*).")
    _send_home(wa)

def _open_sessions(wa: str) -> None:
    send_whatsapp_text(wa, "🗓 *Sessions*\n(Coming soon: today's schedule with attendee names and actions.)")
    _send_home(wa)

# ──────────────────────────────────────────────────────────────────────────────
# NLP handling (stub execution)
# ──────────────────────────────────────────────────────────────────────────────
def _handle_nlp_command(wa: str, body: str) -> bool:
    """
    Try to interpret admin free-text commands.
    Returns True if handled, False if not matched.
    """
    cmd = parse_admin_command(body)
    if cmd:
        intent = cmd["intent"]
        if intent == "book_single":
            send_whatsapp_text(
                wa,
                f"✅ Booking noted: {cmd['name']} on {cmd['date']} at {cmd['time']}."
            )
            return True
        if intent == "book_recurring":
            send_whatsapp_text(
                wa,
                f"✅ Recurring booking: {cmd['name']} every {cmd['weekday']} at {cmd['time']} for {cmd['weeks']} weeks."
            )
            return True

    client_cmd = parse_admin_client_command(body)
    if client_cmd:
        intent = client_cmd["intent"]
        if intent == "add_client":
            send_whatsapp_text(
                wa,
                f"👤 Added client: {client_cmd['name']} ({client_cmd['number']}) [stub]."
            )
            return True
        if intent == "update_dob":
            send_whatsapp_text(
                wa,
                f"📅 Updated DOB for {client_cmd['name']} to {client_cmd['day']}/{client_cmd['month']}."
            )
            return True
        if intent == "update_medical":
            send_whatsapp_text(
                wa,
                f"📝 Medical note updated for {client_cmd['name']}: {client_cmd['note']}."
            )
            return True
        if intent == "cancel_next":
            send_whatsapp_text(
                wa,
                f"❌ Cancelled next session for {client_cmd['name']}."
            )
            return True
        if intent == "off_sick_today":
            send_whatsapp_text(
                wa,
                f"🤒 Marked {client_cmd['name']} as off sick today."
            )
            return True
        if intent == "no_show_today":
            send_whatsapp_text(
                wa,
                f"⚠️ Marked {client_cmd['name']} as no show today."
            )
            return True

    return False

# ──────────────────────────────────────────────────────────────────────────────
# Entry point called from router
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(wa: str, msg_id: Optional[str] = None, body: str = "", btn_id: Optional[str] = None) -> None:
    try:
        wa = normalize_wa(wa)
        t = (body or "").strip()

        # 1) Button clicks
        if btn_id:
            if btn_id == BTN_INBOX:    _open_inbox(wa); return
            if btn_id == BTN_CLIENTS:  _open_clients(wa); return
            if btn_id == BTN_SESSIONS: _open_sessions(wa); return
            if btn_id == BTN_BACK:     _send_home(wa); return
            _send_home(wa); return

        # 2) Greetings → menu
        if t.lower() in {"", "hi", "hello", "hey", "help", "admin", "menu"}:
            _send_home(wa); return

        # 3) NLP free-text commands
        if _handle_nlp_command(wa, t):
            return

        # 4) Shortcuts
        if t.lower() in {"inbox"}:    _open_inbox(wa); return
        if t.lower() in {"clients"}:  _open_clients(wa); return
        if t.lower() in {"sessions"}: _open_sessions(wa); return

        # 5) Fallback
        _send_home(wa)

    except Exception:
        logging.exception("handle_admin_action failed")
        try:
            _send_home(wa)
        except Exception:
            logging.exception("handle_admin_action fallback failed (send_home)")
