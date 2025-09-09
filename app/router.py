# app/router.py
# app/router.py
from __future__ import annotations

import hashlib
import logging
from typing import Optional, Tuple

from flask import request

from .config import ADMIN_NUMBERS, VERIFY_TOKEN
from .utils import normalize_wa, send_whatsapp_text
from .admin import handle_admin_action
from .crud import (
    client_exists_by_wa,
    find_client_by_wa,
    upsert_public_client,
    inbox_upsert,
    lead_set_expectation,
    lead_peek_expectation,
    lead_pop_expectation,
)

# ──────────────────────────────────────────────────────────────────────────────
# Public (lead/FAQ) flow
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
    t = _normalize(text)

    # Numeric picks
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

    # Greetings → menu
    if any(k in t for k in ["hi", "hello", "hey", "morning", "afternoon", "evening"]):
        return "menu", None

    # Keyword map
    if "price" in t or "cost" in t or "fee" in t:
        return "pricing", None
    if "address" in t or "parking" in t or "where" in t or "located" in t:
        return "address", None
    if "schedule" in t or "time" in t or "open" in t or "hour" in t:
        return "schedule", None
    if "group" in t or "size" in t:
        return "group_sizes", None
    if "equip" in t or "reformer" in t or "chair" in t or "mat" in t:
        return "equipment", None
    if "start" in t or "assessment" in t or "begin" in t:
        return "how_to_start", None
    if "book" in t or "reserve" in t:
        return "book_request", None
    if "contact" in t or "call" in t or "email" in t or "whatsapp" in t:
        return "contact", None

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
    return "Thanks! How can we help today?"

def _handle_public_message(wa: str, body: str) -> None:
    """
    Lead/FAQ flow with a lightweight name-capture gate for booking requests.
    - If user says 'book' and we don't have their name, ask for name once.
    - Next inbound becomes their name -> save -> write inbox booking_request.
    - Always show menu after replying.
    """
    text_in = (body or "").strip()
    lower = text_in.lower()

    # If we previously asked for name, capture it now
    expecting = lead_peek_expectation(wa)
    if expecting == "name" and text_in:
        # Accept short or long names; trim and cap length a bit
        name = text_in[:80].strip()
        if len(name) < 2:
            send_whatsapp_text(wa, "Please send your *full name* (at least 2 characters).")
            return
        try:
            upsert_public_client(wa, name)
        except Exception:
            logging.exception("Failed to save lead name")
        # clear the expectation
        lead_pop_expectation(wa)

        # Now log the booking request to the admin inbox
        try:
            title = "New booking request"
            inbox_body = f"From {name} ({wa})\nMessage: (requested to book)"
            inbox_upsert(
                kind="booking_request",
                title=title,
                body=inbox_body,
                client_id=None,
                session_id=None,
                source="whatsapp",
                status="open",
                is_unread=True,
                action_required=True,
            )
            # notify admins
            for admin in ADMIN_NUMBERS:
                send_whatsapp_text(
                    normalize_wa(admin),
                    f"📩 *New booking request* from {name} ({wa})"
                )
        except Exception:
            logging.exception("Failed to write booking request to inbox")

        send_whatsapp_text(
            wa,
            "✅ Thanks, we’ve sent your request to the studio. "
            "An instructor will follow up shortly.\n\n" + _public_menu()
        )
        return

    # Normal intent routing
    intent, _ = _intent_and_payload(text_in)

    # “book” clicked/typed: ensure we have a name
    if intent == "book_request":
        # Check if we already have a name on file
        client = None
        try:
            client = find_client_by_wa(wa)
        except Exception:
            logging.exception("find_client_by_wa failed")

        has_name = bool(client and client.get("name"))
        if not has_name:
            # Save a shell lead if needed and ask for name
            try:
                if not client:
                    upsert_public_client(wa, None)
            except Exception:
                logging.exception("lead shell upsert failed")

            lead_set_expectation(wa, "name")
            send_whatsapp_text(
                wa,
                "Great! Before we book, what’s your *full name*?\n"
                "Reply with your name (e.g., *Nadine Jacobs*)."
            )
            return

        # We have a name already → log request immediately
        try:
            nm = client["name"]
            title = "New booking request"
            inbox_body = f"From {nm} ({wa})\nMessage: (requested to book)"
            inbox_upsert(
                kind="booking_request",
                title=title,
                body=inbox_body,
                client_id=client["id"],
                session_id=None,
                source="whatsapp",
                status="open",
                is_unread=True,
                action_required=True,
            )
            for admin in ADMIN_NUMBERS:
                send_whatsapp_text(
                    normalize_wa(admin),
                    f"📩 *New booking request* from {nm} ({wa})"
                )
        except Exception:
            logging.exception("Failed to write booking request to inbox")

        send_whatsapp_text(
            wa,
            _faq_response(intent) + "\n\n" + _public_menu()
        )
        return

    # All other FAQ/menu replies (your existing logic)
    if intent == "menu":
        send_whatsapp_text(
            wa,
            "Welcome to *PilatesHQ*! 👋\nHow can we help today?\n" + _public_menu()
        )
    else:
        send_whatsapp_text(
            wa,
            _faq_response(intent) + "\n\n" + _public_menu()
        )


    # Normal intent routing
    intent, _ = _intent_and_payload(text_in)

    # “book” clicked/typed: ensure we have a name
    if intent == "book_request":
        # Check if we already have a name on file
        client = None
        try:
            client = find_client_by_wa(wa)
        except Exception:
            logging.exception("find_client_by_wa failed")

        has_name = bool(client and client.get("name"))
        if not has_name:
            # Save a shell lead if needed and ask for name
            try:
                if not client:
                    upsert_public_client(wa, None)
            except Exception:
                logging.exception("lead shell upsert failed")

            lead_set_expectation(wa, "name")
            send_whatsapp_text(
                wa,
                "Great! Before we book, what’s your *full name*?\n"
                "Reply with your name (e.g., *Nadine Jacobs*)."
            )
            return

        # We have a name already → log request immediately
        try:
            nm = client["name"]
            title = "New booking request"
            inbox_body = f"From {nm} ({wa})\nMessage: (requested to book)"
            inbox_upsert(
                kind="booking_request",
                title=title,
                body=inbox_body,
                client_id=client["id"],
                session_id=None,
                source="whatsapp",
                status="open",
                is_unread=True,
                action_required=True,
            )
            for admin in ADMIN_NUMBERS:
                send_whatsapp_text(
                    normalize_wa(admin),
                    f"📩 *New booking request* from {nm} ({wa})"
                )
        except Exception:
            logging.exception("Failed to write booking request to inbox")

        send_whatsapp_text(
            wa,
            _faq_response(intent) + "\n\n" + _public_menu()
        )
        return

    # All other FAQ/menu replies (your existing logic)
    if intent == "menu":
        send_whatsapp_text(
            wa,
            "Welcome to *PilatesHQ*! 👋\nHow can we help today?\n" + _public_menu()
        )
    else:
        send_whatsapp_text(
            wa,
            _faq_response(intent) + "\n\n" + _public_menu()
        )

# ──────────────────────────────────────────────────────────────────────────────
# Flask wiring
# ──────────────────────────────────────────────────────────────────────────────

def register_routes(app):
    @app.get("/")
    def root():
        return "ok", 200

    @app.get("/webhook")
    def webhook_verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
            return challenge, 200
        return "forbidden", 403

    @app.post("/webhook")
    def webhook():
        try:
            data = request.get_json(force=True, silent=True) or {}
            entry = (data.get("entry") or [])
            if not entry: return "ok", 200
            changes = (entry[0].get("changes") or [])
            if not changes: return "ok", 200
            value = changes[0].get("value") or {}
            msgs = value.get("messages") or []
            if not msgs: return "ok", 200

            msg = msgs[0]
            from_wa_raw = msg.get("from") or ""
            from_wa = normalize_wa(from_wa_raw)
            msg_type = msg.get("type")

            # Pull text
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
                body = ""

            # Route: Admin vs Public
            if from_wa in ADMIN_NUMBERS:
                # Always show admin menu after actions (inside handler)
                try:
                    handle_admin_action(from_wa, msg.get("id"), body)
                except Exception:
                    logging.exception("admin handler failed")
            else:
                _handle_public_message(from_wa, body)

            return "ok", 200

        except Exception:
            logging.exception("webhook failed")
            return "error", 500
