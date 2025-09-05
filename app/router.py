# app/router.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import request, jsonify
from sqlalchemy import text

from .config import VERIFY_TOKEN, NADINE_WA
from .utils import (
    normalize_wa,
    send_whatsapp_text,
    send_whatsapp_buttons,
)
from .db import get_session
from .admin import handle_admin_action
from .crud import (
    find_next_upcoming_booking_by_wa,
    create_cancel_request,
)

# ─────────────────────────────────────────────────────────────
# Public endpoints registration
# main.py calls: from .router import register_routes
# ─────────────────────────────────────────────────────────────

def register_routes(app):
    @app.get("/health")
    def health():
        return "ok", 200

    # Meta/WhatsApp webhook verification
    @app.get("/webhook")
    def verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "forbidden", 403

    # WhatsApp webhook receiver
    @app.post("/webhook")
    def webhook():
        try:
            data = request.get_json(force=True, silent=True) or {}
            # Minimal guard
            if "entry" not in data:
                return "ok", 200

            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    statuses = value.get("statuses", [])

                    # 1) Handle delivered/read/status callbacks if you want
                    if statuses:
                        # Optional: log delivery receipts
                        logging.debug(f"[WA STATUS] {statuses}")
                        continue

                    # 2) Handle inbound messages (text, interactive replies, etc.)
                    for msg in messages:
                        _handle_single_message(msg)

            return "ok", 200
        except Exception:
            logging.exception("webhook error")
            return "error", 500


# ─────────────────────────────────────────────────────────────
# Message dispatcher
# ─────────────────────────────────────────────────────────────

def _handle_single_message(msg: Dict[str, Any]) -> None:
    """
    Parse an inbound WhatsApp message and route it:
      - If from admin -> handle_admin_action()
      - If client typed 'CANCEL' -> queue cancel request, notify admin
      - If interactive button from admin -> handle_admin_action() with the payload id
      - Else: lightweight default reply (optional)
    """
    from_wa = normalize_wa(_safe_get(msg, ["from"]))
    if not from_wa:
        logging.warning("[webhook] missing sender number")
        return

    is_interactive = "interactive" in msg
    text_body = _extract_text(msg)  # lowercased for matching, raw for admin handling below
    interactive_id = _extract_interactive_id(msg)  # button/list reply id if present

    # Decide if sender is the admin
    admin_wa = normalize_wa(NADINE_WA)
    is_admin = admin_wa and (from_wa == admin_wa)

    # If interactive reply exists (buttons/list), pass to admin handler if admin; else ignore
    if is_interactive and interactive_id:
        if is_admin:
            logging.info(f"[admin interactive] {interactive_id}")
            # Admin actions (e.g., ADMIN_CANCEL_REQ_CONFIRM_123)
            handle_admin_action(from_wa, interactive_id)
        else:
            logging.info(f"[client interactive ignored] {interactive_id}")
        return

    # Admin free text commands (existing admin console)
    if is_admin:
        # Pass raw text to admin handler so it can parse rich commands/actions
        handle_admin_action(from_wa, text_body or "")
        return

    # Client plain-text intents
    _handle_client_text_intents(from_wa, text_body, original_msg=msg)


# ─────────────────────────────────────────────────────────────
# Client intents (non-admin)
# ─────────────────────────────────────────────────────────────

def _handle_client_text_intents(sender_wa: str, text_body: str, original_msg: Dict[str, Any]) -> None:
    """
    Currently supports:
      - 'cancel' → enqueue cancel request (no DB mutation), notify admin with buttons.
      - (you can add 'help', 'book', etc. here later)
    """
    txt = (text_body or "").strip().lower()

    if txt == "cancel":
        nxt = find_next_upcoming_booking_by_wa(sender_wa)
        if not nxt:
            send_whatsapp_text(
                sender_wa,
                "We couldn't find an upcoming booking under your number. Reply HELP if you need assistance."
            )
            return

        req = create_cancel_request(
            booking_id=nxt["booking_id"],
            client_id=nxt["client_id"],
            session_id=nxt["session_id"],
            reason="client texted CANCEL",
            via="client",
        )

        # Acknowledge to client (no mutation yet)
        hhmm = str(nxt["start_time"])[:5]
        send_whatsapp_text(
            sender_wa,
            f"Thanks! We've notified the studio about canceling your {hhmm} session. We'll confirm shortly."
        )

        # Notify admin with actionable buttons
        admin_wa = normalize_wa(NADINE_WA)
        if admin_wa:
            nm = nxt.get("name") or "client"
            msg = (
                f"❗Cancel request #{req['id']}\n"
                f"👤 {nm}\n"
                f"📅 {nxt['session_date']} {hhmm}\n\n"
                f"Choose: Confirm / Decline / Reschedule"
            )
            send_whatsapp_buttons(
                admin_wa,
                msg,
                [
                    {"id": f"ADMIN_CANCEL_REQ_CONFIRM_{req['id']}", "title": "Confirm Cancel"},
                    {"id": f"ADMIN_CANCEL_REQ_DECLINE_{req['id']}", "title": "Decline"},
                    {"id": f"ADMIN_CANCEL_REQ_RESCH_{req['id']}",   "title": "Reschedule"},
                ],
            )
        return

    # Fallback default (keep it minimal for now)
    send_whatsapp_text(
        sender_wa,
        "Hi! I can help with session reminders and bookings. Reply CANCEL to request a cancellation of your next session, or HELP to see options."
    )


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _extract_text(msg: Dict[str, Any]) -> str:
    """
    Returns a lowercased message body for matching.
    For admin commands we already pass the lowercased string to keep parsing simple.
    """
    # simple text
    if "text" in msg and isinstance(msg["text"], dict):
        body = msg["text"].get("body") or ""
        return body.strip()
    # interactive list or button might carry a 'description' or 'title'
    inter = msg.get("interactive")
    if inter:
        # button_reply has a 'title'; list_reply has a 'title' too
        br = inter.get("button_reply") or {}
        lr = inter.get("list_reply") or {}
        title = br.get("title") or lr.get("title") or ""
        return title.strip()
    return ""

def _extract_interactive_id(msg: Dict[str, Any]) -> Optional[str]:
    """
    Pulls the reply id of a button/list interactive response (e.g. ADMIN_CANCEL_REQ_CONFIRM_123).
    """
    inter = msg.get("interactive")
    if not inter:
        return None
    br = inter.get("button_reply")
    if br and isinstance(br, dict):
        return br.get("id")
    lr = inter.get("list_reply")
    if lr and isinstance(lr, dict):
        return lr.get("id")
    return None

def _safe_get(d: Dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur = d
    try:
        for p in path:
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return default
        return cur if cur is not None else default
    except Exception:
        return default
