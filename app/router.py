# app/router.py
from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Optional, Tuple, Dict, Any

from flask import request

from .config import ADMIN_NUMBERS, VERIFY_TOKEN, NADINE_WA
from .utils import (
    normalize_wa,
    send_whatsapp_text,
    send_whatsapp_buttons,
    send_whatsapp_list,
)
from .admin import handle_admin_action
from .crud import client_exists_by_wa, upsert_public_client, inbox_upsert

# ──────────────────────────────────────────────────────────────────────────────
# Minimal in-memory session (swap for Redis in prod)
# ──────────────────────────────────────────────────────────────────────────────
SESS: Dict[str, Dict[str, Any]] = {}   # {wa: {"phase": str, "name": str, "ts": int}}
TTL = 60 * 30  # 30 minutes

def _now() -> int:
    return int(time.time())

def _get_sess(wa: str) -> Dict[str, Any]:
    # GC stale
    stale = [k for k, v in SESS.items() if _now() - v.get("ts", 0) > TTL]
    for k in stale:
        del SESS[k]
    s = SESS.get(wa, {"phase": "idle", "name": None, "ts": _now()})
    s["ts"] = _now()
    SESS[wa] = s
    return s

def _reset_sess(wa: str) -> None:
    if wa in SESS:
        del SESS[wa]

# ──────────────────────────────────────────────────────────────────────────────
# Public UX: Brand-first welcome + short paths
# ──────────────────────────────────────────────────────────────────────────────
BTN_MEET     = "g_meet"
BTN_BOOK     = "g_book"
BTN_PRICE    = "g_price"
BTN_BOOK_NOW = "g_book_now"

def _welcome_buttons() -> list[dict]:
    return [
        {"title": "👩‍🏫 Meet Nadine",     "id": BTN_MEET},
        {"title": "🗓️ Book a Class",      "id": BTN_BOOK},
        {"title": "💳 Pricing & Specials", "id": BTN_PRICE},
    ]

def _safe_send_buttons(wa: str, body: str, buttons: list[dict]) -> None:
    try:
        logging.info("send_buttons → to=%s title=%s", wa, (body or "").splitlines()[0])
        res = send_whatsapp_buttons(wa, body, buttons)
        if not isinstance(res, dict) or res.get("error") or (res.get("messaging_product") is None and res.get("status_code") not in (200, 201)):
            logging.error("interactive failed or unexpected response; will fallback. res=%s", res)
            send_whatsapp_text(wa, body + "\n\nReply: Meet Nadine | Book | Pricing")
    except Exception:
        logging.exception("interactive send raised; falling back to text")
        send_whatsapp_text(wa, body + "\n\nReply: Meet Nadine | Book | Pricing")

def _safe_send_list(wa: str, body: str, button_text: str, section_title: str, rows: list[dict]) -> None:
    try:
        logging.info("send_list → to=%s title=%s", wa, (body or "").splitlines()[0])
        res = send_whatsapp_list(wa, body, button_text, section_title, rows)
        if not isinstance(res, dict) or res.get("error") or (res.get("messaging_product") is None and res.get("status_code") not in (200, 201)):
            logging.error("list failed or unexpected response; will fallback. res=%s", res)
            send_whatsapp_text(wa, body + "\n\nIf the list didn’t appear, type: address / schedule / equipment / groups / start")
    except Exception:
        logging.exception("list send raised; falling back to text")
        send_whatsapp_text(wa, body + "\n\nIf the list didn’t appear, type: address / schedule / equipment / groups / start")

def _send_brand_welcome(wa: str) -> None:
    body = (
        "✨ Welcome to *PilatesHQ*!\n"
        "We keep classes small, personal, and fun so you feel stronger after every session.\n\n"
        "Choose an option:"
    )
    _safe_send_buttons(wa, body, _welcome_buttons())

MEET_NADINE = (
    "👩‍🏫 *Meet Nadine*\n"
    "Founder & Lead Instructor at *PilatesHQ*\n\n"
    "Nadine is a certified Pilates instructor with a passion for helping people move better, "
    "recover from injuries, and feel stronger in their daily lives. With years of experience in both "
    "group classes and one-to-one sessions, she tailors Reformer Pilates to each person’s needs — "
    "from core strength and posture to rehabilitation.\n\n"
    "✨ Small classes • Personal coaching • Calm, encouraging style.\n\n"
    "Ready to experience PilatesHQ with Nadine?"
)

def _send_meet_nadine(wa: str) -> None:
    _safe_send_buttons(wa, MEET_NADINE, [{"title": "🗓️ Book a Class", "id": BTN_BOOK}])

def _send_pricing(wa: str) -> None:
    body = (
        "💳 *Pricing & Opening Special*\n"
        "(now available)\n\n"
        "• 👥 Group Class (max 6) — R180 per person\n"
        "• 👩‍🤝‍👩 Duo Session — R250 per person\n"
        "• 👤 Private 1-1 — R300\n\n"
        "✨ Small classes • Personal coaching • Guided by Nadine"
    )
    _safe_send_buttons(wa, body, [{"title": "🗓️ Book Now", "id": BTN_BOOK_NOW}])

def _faq_text(intent: str) -> str:
    if intent == "pricing":
        return ("💳 *Pricing & Specials*\n"
                "• Group (max 6) — R180 pp\n"
                "• Duo — R250 pp\n"
                "• Private 1-1 — R300")
    if intent == "address":
        return "📍 *Address*\nPilatesHQ — 71 Grant Ave, Norwood, Johannesburg\nSafe off-street parking."
    if intent == "schedule":
        return "🗓️ *Schedule*\nWeekdays 06:00–18:00 • Saturday 08:00–10:00"
    if intent == "group_sizes":
        return "👥 *Group sizes*\nCapped at 6 for personal coaching. Duos and privates available."
    if intent == "equipment":
        return "🧰 *Equipment*\nReformers, Wall Units, Wunda Chairs, small props, and mats."
    if intent == "how_to_start":
        return "🚀 *How to start*\nMost begin with a 1:1 assessment. Reply *Book* to start a lead."
    return "How can we help?"

def _normalize(text: str) -> str:
    return (text or "").strip().lower()

def _public_intent(text: str) -> str:
    t = _normalize(text)
    if any(k in t for k in ["hi", "hello", "hey", "morning", "afternoon", "evening", "menu", "start"]):
        return "welcome"
    if "book" in t or "booking" in t:
        return "book"
    if "price" in t or "special" in t:
        return "pricing"
    if "address" in t or "parking" in t or "where" in t:
        return "address"
    if "schedule" in t or "hours" in t or "open" in t or "time" in t:
        return "schedule"
    if "group" in t and "size" in t:
        return "group_sizes"
    if "equip" in t or "reformer" in t or "chair" in t or "mat" in t:
        return "equipment"
    if "start" in t or "assessment" in t:
        return "how_to_start"
    return "welcome"

# Lead capture: 2-step (Name → open prompt) and admin handover
ASK_NAME = "👋 Great! Before we get started, could I have your *full name* so Nadine can greet you properly?"

def _ask_name(wa: str) -> None:
    s = _get_sess(wa)
    s["phase"] = "awaiting_name"
    logging.info("public flow → ask_name to=%s", wa)
    send_whatsapp_text(wa, ASK_NAME)

ASK_DETAILS_TEMPLATE = (
    "Lovely to meet you, *{name}*! 🌸\n"
    "To help Nadine match you to the right class, could you share—in your own words—any of the following:\n"
    "• If you’ve done Pilates before (or if this is your first time)\n"
    "• Your preference (group, duo with partner, or private 1-1)\n"
    "• Your ideal time window (early mornings, midday, afternoons 3–5pm, or evenings 5–7pm)\n"
    "• Anything medical we should know (doctor’s clearance needed for pre-existing injuries)\n"
    "• And if you heard about us via a friend, signboard, or Instagram ✨"
)

def _ask_details(wa: str, name: str) -> None:
    s = _get_sess(wa)
    s["phase"] = "awaiting_details"
    s["name"] = name
    logging.info("public flow → ask_details to=%s name=%s", wa, name)
    send_whatsapp_text(wa, ASK_DETAILS_TEMPLATE.format(name=name))

THANK_YOU_TEMPLATE = (
    "✅ Thanks so much, *{name}*! Nadine will personally reach out to confirm your booking and guide you from here.\n"
    "We’re excited to welcome you to PilatesHQ soon 🌸"
)

def _extract_name(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None
    parts = re.findall(r"[A-Za-z'’\-]+", t)
    if len(parts) >= 2:
        return " ".join(p.capitalize() for p in parts[:4])
    if len(parts) == 1:
        return parts[0].capitalize()
    return None

def _summarise_for_admin(wa: str, name: str, details: str) -> str:
    s = (details or "").lower()
    exp = "not provided"
    if any(k in s for k in ["first time", "new to pilates", "never done", "beginner"]): exp = "First time"
    elif any(k in s for k in ["done pilates", "have pilates", "experienced", "previous pilates"]): exp = "Has done Pilates"

    pref = "not provided"
    if "duo" in s or "partner" in s or "couple" in s: pref = "Duo with partner"
    elif "group" in s or "class" in s:                pref = "Group"
    elif any(k in s for k in ["private", "1-1", "1:1", "single"]): pref = "Private 1-1"

    timew = "not provided"
    if any(k in s for k in ["before 8", "early", "morning"]): timew = "Early mornings"
    if any(k in s for k in ["midday", "lunch"]):               timew = "Midday"
    if any(k in s for k in ["afternoon", "3-5", "3pm", "4pm", "5pm"]): timew = "Afternoons (3–5pm)"
    if any(k in s for k in ["evening", "after 5", "5-7", "6pm", "7pm"]): timew = "Evenings (5–7pm)"

    medical = "not mentioned"
    if any(k in s for k in ["injur", "surgery", "pain", "condition", "back", "knee", "shoulder", "doctor", "clearance"]): medical = "Mentioned (check clearance)"
    if any(k in s for k in ["no medical", "no issues", "none", "fit", "healthy"]):                                        medical = "None"

    ref = "not provided"
    if any(k in s for k in ["friend", "referr", "word of mouth"]): ref = "Friend/Referral"
    elif "sign" in s or "signboard" in s:                          ref = "Signboard"
    elif "instagram" in s or "insta" in s:                         ref = "Instagram"
    elif "facebook" in s or "meta" in s:                           ref = "Facebook"
    elif "google" in s or "search" in s:                           ref = "Google/Search"
    elif "website" in s or "site" in s:                            ref = "Website"

    return (
        "📩 New Lead\n"
        f"From: {wa}\n"
        f"Name: {name or '(not provided)'}\n"
        f"Pilates before: {exp}\n"
        f"Preference: {pref}\n"
        f"Time: {timew}\n"
        f"Medical: {medical}\n"
        f"Referral: {ref}"
    )

def _thank_and_handover(wa: str, name: str, raw_reply: str) -> None:
    summary = _summarise_for_admin(wa, name, raw_reply)
    try:
        logging.info("handover → notify Nadine and inbox for wa=%s name=%s", wa, name)
        send_whatsapp_text(normalize_wa(NADINE_WA), summary)
        digest = hashlib.sha256(f"{wa}|{name}|{raw_reply}".encode("utf-8")).hexdigest()
        inbox_upsert(
            kind="lead",
            title="New Lead",
            body=summary,
            source="whatsapp",
            status="open",
            is_unread=True,
            action_required=True,
            digest=digest,
        )
    except Exception:
        logging.exception("Failed to notify/admin-inbox lead")
    send_whatsapp_text(wa, THANK_YOU_TEMPLATE.format(name=name))
    _reset_sess(wa)

def _handle_public_message(wa: str, body: str, btn_id: Optional[str]) -> None:
    try:
        logging.info("public handler start → wa=%s btn_id=%s body_len=%d", wa, btn_id, len(body or ""))
        try:
            if not client_exists_by_wa(wa):
                upsert_public_client(wa, None)
        except Exception:
            logging.exception("Lead upsert failed (non-fatal)")

        if btn_id == BTN_MEET:          _send_meet_nadine(wa); return
        if btn_id in {BTN_BOOK, BTN_BOOK_NOW}: _ask_name(wa); return
        if btn_id == BTN_PRICE:         _send_pricing(wa); return

        sess = _get_sess(wa)
        t = (body or "").strip()

        if sess.get("phase") == "awaiting_name":
            name = _extract_name(t) or "(not provided)"
            _ask_details(wa, name); return

        if sess.get("phase") == "awaiting_details":
            name = sess.get("name") or "(not provided)"
            _thank_and_handover(wa, name, t); return

        intent = _public_intent(body)
        logging.info("public intent resolved → %s", intent)
        if intent == "welcome":
            _send_brand_welcome(wa); return
        send_whatsapp_text(wa, _faq_text(intent))
        _send_brand_welcome(wa)
    except Exception:
        logging.exception("public handler failed")

# ──────────────────────────────────────────────────────────────────────────────
# Flask wiring
# ──────────────────────────────────────────────────────────────────────────────
def register_routes(app):
    @app.get("/")
    def root():
        return "ok", 200

    if "health_router" not in app.view_functions:
        @app.get("/health", endpoint="health_router")
        def health_router():
            return "ok", 200

    @app.get("/webhook")
    def webhook_verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        logging.info("GET /webhook verify mode=%s", mode)
        if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
            return challenge, 200
        return "forbidden", 403

    @app.post("/webhook")
    def webhook():
        logging.info("POST /webhook received")
        try:
            data = request.get_json(force=True, silent=True) or {}
            entry = (data.get("entry") or [])
            if not entry:
                logging.info("no entry[] in payload"); return "ok", 200
            changes = (entry[0].get("changes") or [])
            if not changes:
                logging.info("no changes[] in entry[0]"); return "ok", 200
            value = changes[0].get("value") or {}
            msgs = value.get("messages") or []
            if not msgs:
                logging.info("no messages[] in value"); return "ok", 200

            msg = msgs[0]
            from_wa_raw = msg.get("from") or ""
            from_wa = normalize_wa(from_wa_raw)
            msg_type = msg.get("type")
            logging.info("inbound message → from=%s type=%s", from_wa, msg_type)

            body = ""; btn_id: Optional[str] = None
            if msg_type == "text":
                body = (msg.get("text") or {}).get("body", "") or ""
            elif msg_type == "interactive":
                inter = msg.get("interactive") or {}
                if inter.get("type") == "button_reply":
                    br = inter.get("button_reply") or {}
                    body = br.get("title", "") or ""; btn_id = br.get("id") or None
                elif inter.get("type") == "list_reply":
                    lr = inter.get("list_reply") or {}
                    body = lr.get("title", "") or ""; btn_id = lr.get("id") or None

            if from_wa in ADMIN_NUMBERS:
                logging.info("routing to admin handler for %s", from_wa)
                try:
                    handle_admin_action(from_wa, msg.get("id"), body, btn_id)
                except TypeError:
                    handle_admin_action(from_wa, msg.get("id"), body)
            else:
                logging.info("routing to public handler for %s", from_wa)
                _handle_public_message(from_wa, body, btn_id)

            return "ok", 200

        except Exception:
            logging.exception("webhook failed")
            return "error", 500
