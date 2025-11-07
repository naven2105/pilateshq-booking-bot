"""
client_menu_router.py – Phase 27L+ (Menu Fallback + Invoice Merge + (x) markers)
────────────────────────────────────────────────────────────
Enhancements in this version:
 • Standardised summary formatting: if a sessions array is present,
   rebuild the summary ensuring rescheduled sessions show "(x)".
 • Keeps NLP normalisation and existing flows as-is.
────────────────────────────────────────────────────────────
"""

import os
import logging
import requests
from flask import Blueprint, request, jsonify
from .utils import (
    send_whatsapp_template,
    send_safe_message,
    send_whatsapp_text,
    normalize_wa,
)

bp = Blueprint("client_menu", __name__)
log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
MENU_TEMPLATE = "pilateshq_menu_main"
CLIENT_ALERT_TEMPLATE = "client_generic_alert_us"
GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "35"))
INVOICE_ENDPOINT = f"{WEBHOOK_BASE}/invoices/review-one"


# ─────────────────────────────────────────────────────────────
# NLP normaliser for free-text variants
# ─────────────────────────────────────────────────────────────
def normalise_action(text: str) -> str:
    if not text:
        return ""
    t = text.strip().lower()

    if any(k in t for k in ["schedule", "booking", "class", "session"]):
        return "my_schedule"

    if any(k in t for k in ["invoice", "invoices", "share invoice", "send invoice", "latest invoice", "view invoice"]):
        return "view_invoice"

    return t


# ─────────────────────────────────────────────────────────────
# Summary formatter with “(x)” markers
# ─────────────────────────────────────────────────────────────
def _fmt_line(time_str: str, client_name: str, session_type: str, status: str) -> str:
    t = (time_str or "").strip()
    name = (client_name or "").strip()
    s_type = (session_type or "single").strip()
    st = (status or "").strip().lower()
    mark = " (x)" if st == "rescheduled" else ""
    return f"{t}{mark} • {name} ({s_type})"


def _rebuild_summary_from_sessions(sessions: list) -> str:
    if not isinstance(sessions, list) or not sessions:
        return ""
    def _key(s):
        t = str(s.get("start_time") or "")
        return t.replace("h", ":")
    lines = []
    for s in sorted(sessions, key=_key):
        lines.append(_fmt_line(
            time_str=str(s.get("start_time") or ""),
            client_name=str(s.get("client_name") or ""),
            session_type=str(s.get("session_type") or "single"),
            status=str(s.get("status") or "")
        ))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Menu sender
# ─────────────────────────────────────────────────────────────
def send_client_menu(wa_number: str, name: str = "there"):
    try:
        send_whatsapp_template(wa_number, MENU_TEMPLATE, TEMPLATE_LANG, [name])
        log.info(f"✅ Menu template sent to {wa_number}")
        return {"ok": True}
    except Exception as e:
        log.error(f"❌ send_client_menu failed: {e}")
        send_whatsapp_text(wa_number, "⚠️ Sorry, menu unavailable right now.")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Action handler (buttons + NLP)
# ─────────────────────────────────────────────────────────────
@bp.route("/action", methods=["POST"])
def handle_client_action():
    data = request.get_json(force=True) or {}
    wa_number = normalize_wa(data.get("wa_number", ""))
    name = data.get("name", "there")
    raw_action = (data.get("payload") or data.get("text") or "").strip()
    action = normalise_action(raw_action)
    handled = False

    log.info(f"[client_menu] Action received: raw='{raw_action}', normalised='{action}' from {wa_number}")

    try:
        # 1️⃣ My Schedule
        if action == "my_schedule" and not handled:
            handled = True
            if GAS_WEBHOOK_URL:
                r = requests.post(
                    GAS_WEBHOOK_URL,
                    json={"action": "export_sessions_week", "wa_number": wa_number},
                    timeout=REQUEST_TIMEOUT,
                )
                log.info(f"🔗 export_sessions_week → HTTP {r.status_code}")
                if r.ok:
                    result = r.json() or {}
                    sessions = result.get("sessions") or []
                    # Always prefer rebuilding from rows (guarantees '(x)' markers)
                    summary = _rebuild_summary_from_sessions(sessions) if sessions else str(result.get("summary") or "")
                    if summary:
                        send_whatsapp_template(wa_number, CLIENT_ALERT_TEMPLATE, TEMPLATE_LANG, [summary])
                        return jsonify({"ok": True, "summary": summary}), 200
                    send_whatsapp_text(wa_number, "📭 No booked sessions found in the next 7 days.")
                    return jsonify({"ok": True, "summary": "none"}), 200
            send_whatsapp_text(wa_number, "⚠️ Unable to fetch your schedule right now.")
            return jsonify({"ok": False}), 200

        # 2️⃣ View Latest Invoice
        if action == "view_invoice" and not handled:
            handled = True
            payload = {"client_name": name, "wa_number": wa_number}
            try:
                r = requests.post(INVOICE_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT)
                log.info(f"🧾 Invoice request → HTTP {r.status_code}")
                if r.ok:
                    return jsonify({"ok": True, "routed": "invoice"}), 200
            except Exception as e:
                log.warning(f"Invoice error: {e}")
            send_whatsapp_text(wa_number, "⚠️ Unable to retrieve your invoice right now.")
            return jsonify({"ok": False}), 200

        # 3️⃣ Fallback → show menu again
        log.info(f"[client_menu] Unrecognised input → showing menu to {wa_number}")
        send_client_menu(wa_number, name)
        return jsonify({"ok": False, "fallback": "menu"}), 200

    except Exception as e:
        log.error(f"⚠️ handle_client_action failed: {e}")
        send_whatsapp_text(wa_number, "⚠️ Something went wrong. Please try again later.")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Manual send + health
# ─────────────────────────────────────────────────────────────
@bp.route("/send", methods=["POST"])
def send_menu_api():
    d = request.get_json(force=True) or {}
    wa_number = normalize_wa(d.get("wa_number", ""))
    name = d.get("name", "there")
    return jsonify(send_client_menu(wa_number, name)), 200


@bp.route("/health", methods=["GET"])
@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "client_menu_router", "timeout": REQUEST_TIMEOUT}), 200
