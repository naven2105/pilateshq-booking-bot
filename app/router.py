# app/router.py
from __future__ import annotations

import logging
from typing import Optional, Tuple

from flask import request

from .config import ADMIN_NUMBERS, VERIFY_TOKEN
from .utils import normalize_wa, send_whatsapp_text
from .admin import handle_admin_action
from .crud import client_exists_by_wa, upsert_public_client


# ──────────────────────────────────────────────────────────────────────────────
# Public (Lead / FAQ) helpers
# ──────────────────────────────────────────────────────────────────────────────

PUBLIC_MENU = (
    "—\n"
    "📋 *Menu*\n"
    "1) Pricing\n"
    "2) Address & parking\n"
    "3) Schedule\n"
    "4) Group sizes\n"
    "5) Equipment\n"
    "6) How to start\n"
    "7) Book (send request)\n"
    "8) Contact\n"
    "Reply with a number or keyword (e.g., *pricing*, *address*, *book*)."
)

def _public_menu() -> str:
    return PUBLIC_MENU

def _normalize(text: str) -> str:
    return (text or "").strip().lower()

def _intent_and_payload(text: str) -> Tuple[str, Optional[str]]:
    """
    Map free text to high-level intents.
    Returns (intent, payload) – payload may be None.
    """
    t = _normalize(text)

    # Numeric quick picks
    if t in {"1", "pricing", "price", "prices"}:
        return "pricing", None
    if t in {"2", "address", "parking", "where", "location"}:
        return "address", None
    if t in {"3", "schedule", "hours", "opening", "times"}:
        return "schedule", None
    if t in {"4", "group", "group sizes", "class size"}:
        return "group_sizes", None
    if t in {"5", "equipment", "machines", "reformer"}:
        return "equipment", None
    if t in {"6", "start", "how to start", "assessment"}:
        return "how_to_start", None
    if t in {"7", "book", "booking", "request"}:
        return "book_request", None
    if t in {"8", "contact", "phone", "email"}:
        return "contact", None

    # Friendly greetings → present menu
    if any(k in t for k in ["hi", "hello", "hey", "morning", "afternoon", "evening"]):
        return "menu", None

    # Keyword matching
    if any(k in t for k in ["price", "cost", "fee"]):
        return "pricing", None
    if any(k in t for k in ["address", "parking", "where", "located", "location"]):
        return "address", None
    if any(k in t for k in ["schedule", "time", "open", "hour", "hours"]):
        return "schedule", None
    if any(k in t for k in ["group", "size"]):
        return "group_sizes", None
    if any(k in t for k in ["equip", "reformer", "chair", "mat"]):
        return "equipment", None
    if any(k in t for k in ["start", "assessment", "begin"]):
        return "how_to_start", None
    if any(k in t for k in ["book", "reserve"]):
        return "book_request", None
    if any(k in t for k in ["contact", "call", "email", "whatsapp"]):
        return "contact", None

    # Fallback: show menu
    return "menu", None

def _faq_response(intent: str) -> str:
    if intent == "pricing":
        return (
            "💳 *Pricing*\n"
            "• Group classes from *R180*\n"
            "• 1:1 assessment recommended for newcomers\n"
            "• Packages available – ask us for current specials"
        )
    if intent == "address":
        return (
            "📍 *Address & Parking*\n"
            "PilatesHQ — *71 Grant Ave, Norwood, Johannesburg*\n"
            "Safe off-street parking available."
        )
    if intent == "schedule":
        return (
            "🗓️ *Schedule*\n"
            "• Weekdays: 06:00–18:00\n"
            "• Saturday: 08:00–10:00\n"
            "Ask for today’s availability and we’ll suggest times."
        )
    if intent == "group_sizes":
        return (
            "👥 *Group sizes*\n"
            "Group classes are capped at *6* so coaching stays personal.\n"
            "We also offer duos and privates."
        )
    if intent == "equipment":
        return (
            "🧰 *Equipment*\n"
            "Reformers, Wall Units, Wunda Chairs, small props, and mats.\n"
            "All sessions are guided by certified instructors."
        )
    if intent == "how_to_start":
        return (
            "🚀 *How to start*\n"
            "Most clients begin with a *1:1 assessment* so we can tailor your plan.\n"
            "Reply *Book* and we’ll forward your request to the studio."
        )
    if intent == "contact":
        return (
            "☎️ *Contact*\n"
            "Prefer to chat? Message us here anytime.\n"
            "We’ll introduce you to an instructor to get started."
        )
    if intent == "book_request":
        return (
            "✅ *Booking request noted!*\n"
            "We’ve forwarded your request to the studio. An instructor will confirm time and next steps.\n"
            "If you have preferred days/times, reply with them now."
        )
    # Default
    return "Thanks! How can we help today?"

def _handle_public_message(wa: str, body: str) -> None:
    """
    Lead/FAQ flow:
    - Ensure the number exists in clients table as a lead (name optional).
    - Answer common questions.
    - Always append the menu to keep the conversation discoverable.
    """
    # Ensure (or create) client record as lead
    try:
        exists = client_exists_by_wa(wa)
        if not exists:
            upsert_public_client(wa, None)  # create light lead record
    except Exception:
        logging.exception("Lead upsert failed (non-fatal)")

    intent, _ = _intent_and_payload(body)

    # “Book” also notifies admins
    if intent == "book_request":
        response = _faq_response(intent) + "\n\n" + _public_menu()
        send_whatsapp_text(wa, response)
        try:
            for admin in ADMIN_NUMBERS:
                send_whatsapp_text(
                    normalize_wa(admin),
                    f"📩 *New booking request* from {wa}\n"
                    f"Message: {(body or '').strip() or '(no extra details)'}"
                )
        except Exception:
            logging.exception("Failed to notify admins about a booking request")
        return

    # Normal FAQ reply (always append the menu)
    if intent == "menu":
        send_whatsapp_text(wa, "Welcome to *PilatesHQ*! 👋\nHow can we help today?\n" + _public_menu())
    else:
        send_whatsapp_text(wa, _faq_response(intent) + "\n\n" + _public_menu())


# ──────────────────────────────────────────────────────────────────────────────
# Flask wiring
# ──────────────────────────────────────────────────────────────────────────────

def register_routes(app):
    """
    Mounts:
      GET  /webhook  – Meta verification (hub.mode=subscribe; hub.verify_token; hub.challenge)
      POST /webhook  – WhatsApp Cloud API inbound
      GET  /health   – health check (unique endpoint name to avoid collisions)
      GET  /         – simple OK
    """
    @app.get("/", endpoint="root_ok")
    def root():
        return "ok", 200

    @app.get("/health", endpoint="health_router")
    def health():
        return "ok", 200

    @app.get("/webhook", endpoint="webhook_verify")
    def webhook_verify():
        # Meta’s verification handshake
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
            return challenge, 200
        return "forbidden", 403

    @app.post("/webhook", endpoint="webhook_receive")
    def webhook():
        try:
            data = request.get_json(force=True, silent=True) or {}

            # WhatsApp payload structure (Cloud API):
            # entry[0].changes[0].value.messages[0]
            entry = data.get("entry") or []
            if not entry:
                return "ok", 200
            changes = entry[0].get("changes") or []
            if not changes:
                return "ok", 200
            value = changes[0].get("value") or {}
            msgs = value.get("messages") or []
            if not msgs:
                return "ok", 200

            msg = msgs[0]
            from_wa_raw = msg.get("from") or ""
            from_wa = normalize_wa(from_wa_raw)
            msg_type = msg.get("type")

            # Extract body from text / interactive
            body = ""
            if msg_type == "text":
                body = (msg.get("text") or {}).get("body", "") or ""
            elif msg_type == "interactive":
                inter = msg.get("interactive") or {}
                if inter.get("type") == "button_reply":
                    body = (inter.get("button_reply") or {}).get("title", "") or ""
                elif inter.get("type") == "list_reply":
                    body = (inter.get("list_reply") or {}).get("title", "") or ""
                else:
                    body = ""
            else:
                # Non-text types → treat as empty (we’ll send menu)
                body = ""

            # Admin vs Public
            if from_wa in ADMIN_NUMBERS:
                # Prefer the (wa, reply_id, body) signature for richer commands
                try:
                    handle_admin_action(from_wa, msg.get("id"), body)
                except TypeError:
                    # Fallback to legacy (wa, reply_id)
                    handle_admin_action(from_wa, msg.get("id"))
            else:
                _handle_public_message(from_wa, body)

            return "ok", 200

        except Exception:
            logging.exception("webhook failed")
            return "error", 500
