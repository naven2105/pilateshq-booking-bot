# app/admin.py
from __future__ import annotations

import logging
from typing import Optional, List

from .utils import send_whatsapp_text, send_whatsapp_buttons, normalize_wa
from .config import NADINE_WA


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
    # You can also pass dicts: [{"title":"Inbox","id": BTN_INBOX}, ...]
    # Our utils auto-generate IDs if missing, but we keep explicit ids stable.
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
    # TODO: render unread/action-required counts from admin_inbox later
    send_whatsapp_text(wa, "📥 *Inbox*\n(Coming soon: unread/action required counts and quick actions.)")
    _send_home(wa)

def _open_clients(wa: str) -> None:
    # TODO: ask for a 3+ char search prefix, then show a list picker
    send_whatsapp_text(wa, "👤 *Clients*\nType the first 3+ letters to search (e.g., *nad*).")
    _send_home(wa)

def _open_sessions(wa: str) -> None:
    # TODO: show today's schedule with names; add quick filters
    send_whatsapp_text(wa, "🗓 *Sessions*\n(Coming soon: today's schedule with attendee names and actions.)")
    _send_home(wa)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point called from router
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(wa: str, msg_id: Optional[str] = None, body: str = "", btn_id: Optional[str] = None) -> None:
    """
    Called by router for any inbound admin message.

    Behavior:
      - If the admin typed a greeting/help/menu ⇒ show the home buttons.
      - If the admin tapped a button ⇒ route by btn_id.
      - Otherwise ⇒ default to home (keeps UX discoverable).
    """
    try:
        wa = normalize_wa(wa)
        t = (body or "").strip().lower()

        # 1) Button clicks take priority (router passes btn_id for interactive replies)
        if btn_id:
            if btn_id == BTN_INBOX:
                _open_inbox(wa)
                return
            if btn_id == BTN_CLIENTS:
                _open_clients(wa)
                return
            if btn_id == BTN_SESSIONS:
                _open_sessions(wa)
                return
            if btn_id == BTN_BACK:
                _send_home(wa)
                return
            # Unknown button → just show home
            _send_home(wa)
            return

        # 2) Text commands that should open the menu
        if t in {"", "hi", "hello", "hey", "help", "admin", "menu"}:
            _send_home(wa)
            return

        # 3) Simple typed shortcuts
        if t in {"inbox"}:
            _open_inbox(wa)
            return
        if t in {"clients", "client"}:
            _open_clients(wa)
            return
        if t in {"sessions", "session"}:
            _open_sessions(wa)
            return

        # 4) Fallback: show home so the admin always sees available actions
        _send_home(wa)

    except Exception:
        logging.exception("handle_admin_action failed")
        # Keep the UX resilient — send a home menu even on failure
        try:
            _send_home(wa)
        except Exception:
            logging.exception("handle_admin_action fallback failed (send_home)")
