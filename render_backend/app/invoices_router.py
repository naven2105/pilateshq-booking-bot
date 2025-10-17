"""
invoices_router.py
───────────────────────────────────────────────
Handles Nadine’s invoice review workflow via WhatsApp.

Endpoints:
 - /invoices/review       → list all draft invoices
 - /invoices/review-one   → review a specific client's invoice
 - /invoices/send         → deliver invoice to client (uses invoices.py)
 - /invoices/edit         → reply with Google Sheet link
 - /invoices/callback     → handles Meta button postbacks
 - /invoices              → health check

Integrates with Google Apps Script (Invoices tab) for real data.
───────────────────────────────────────────────
"""

import os
import requests
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from . import invoices
from .utils import send_whatsapp_template, send_whatsapp_text

bp = Blueprint("invoices_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment Variables ────────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# Templates
TPL_ADMIN_GENERIC = "admin_generic_alert_us"
TPL_ADMIN_INVOICE_REVIEW = "client_invoice_review_us"  # Meta template with buttons


# ─────────────────────────────────────────────────────────────
# 1️⃣  LIST DRAFT INVOICES
# ─────────────────────────────────────────────────────────────
@bp.route("/review", methods=["POST"])
def list_draft_invoices():
    """Triggered when Nadine types 'review invoices' on WhatsApp."""
    try:
        payload = {"action": "list_draft_invoices", "sheet_id": SHEET_ID}
        resp = requests.post(GAS_INVOICE_URL, json=payload, timeout=10)
        result = resp.json() if resp.ok else {"ok": False, "message": "Could not fetch invoices."}
        msg = result.get("message", "⚠️ No response from Apps Script.")

        send_whatsapp_text(NADINE_WA, f"📋 {msg}")
        log.info(f"[invoices_router] Draft invoices listed → {msg}")
        return jsonify({"ok": True, "message": msg})
    except Exception as e:
        log.error(f"[invoices_router] list_draft_invoices error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 2️⃣  REVIEW ONE CLIENT INVOICE
# ─────────────────────────────────────────────────────────────
@bp.route("/review-one", methods=["POST"])
def review_one_invoice():
    """Triggered when Nadine types 'invoice {client_name}'."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()
        month_spec = data.get("month_spec", "this month")

        if not client_name:
            return jsonify({"ok": False, "error": "Missing client name"}), 400

        payload = {"action": "list_draft_invoices", "sheet_id": SHEET_ID}
        resp = requests.post(GAS_INVOICE_URL, json=payload, timeout=10)
        available = resp.json().get("message", "") if resp.ok else ""
        exists = client_name.lower() in available.lower()

        month_text = datetime.now().strftime("%b %Y")
        variable_text = f"{client_name} - {month_text}"

        if exists:
            send_whatsapp_template(
                to=NADINE_WA,
                name=TPL_ADMIN_INVOICE_REVIEW,
                lang=TEMPLATE_LANG,
                variables=[variable_text],
            )
            msg = f"📑 Invoice review sent for {variable_text}"
        else:
            send_whatsapp_text(
                NADINE_WA,
                f"⚠️ No draft invoice found for {client_name}. Please run 'generate invoices' first."
            )
            msg = f"No draft invoice found for {client_name}"

        log.info(f"[invoices_router] {msg}")
        return jsonify({"ok": True, "message": msg})
    except Exception as e:
        log.error(f"[invoices_router] review_one_invoice error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 3️⃣  META BUTTON CALLBACK HANDLER
# ─────────────────────────────────────────────────────────────
@bp.route("/callback", methods=["POST"])
def handle_invoice_callback():
    """Meta button postbacks (Send Invoice / Edit Later)."""
    try:
        data = request.get_json(force=True)
        action = data.get("action", "").lower()
        client_name = data.get("client_name", "")
        wa_number = data.get("wa_number", "")
        client_id = data.get("client_id")
        month_spec = data.get("month_spec", "this month")

        if action == "send_invoice":
            invoices.send_invoice(wa_number, client_id, client_name, month_spec)
            payload = {"action": "mark_invoice_sent", "sheet_id": SHEET_ID, "client_name": client_name}
            try:
                requests.post(GAS_INVOICE_URL, json=payload, timeout=10)
            except Exception as e:
                log.warning(f"[callback] Failed to mark invoice as sent: {e}")
            send_whatsapp_text(NADINE_WA, f"✅ Invoice sent to {client_name}")
            return jsonify({"ok": True, "action": "sent"})

        elif action == "edit_invoice":
            sheet_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"
            msg = (
                f"✏️ To edit *{client_name}'s* invoice for {month_spec}, "
                f"open the Invoices tab:\n{sheet_link}\n\n"
                "Make changes and set status = 'edited' when done."
            )
            send_whatsapp_text(NADINE_WA, msg)
            return jsonify({"ok": True, "action": "edit"})

        else:
            send_whatsapp_text(NADINE_WA, "⚠️ Unknown button action received.")
            return jsonify({"ok": False, "error": "Unknown action"})

    except Exception as e:
        log.error(f"[invoices_router] handle_invoice_callback error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 4️⃣  MANUAL SEND ENDPOINT
# ─────────────────────────────────────────────────────────────
@bp.route("/send", methods=["POST"])
def send_invoice_to_client():
    """Triggered manually or by callback handler."""
    try:
        data = request.get_json(force=True)
        client_id = data.get("client_id")
        client_name = data.get("client_name")
        wa_number = data.get("wa_number")
        month_spec = data.get("month_spec", "this month")

        invoices.send_invoice(wa_number, client_id, client_name, month_spec)

        payload = {"action": "mark_invoice_sent", "sheet_id": SHEET_ID, "client_name": client_name}
        try:
            requests.post(GAS_INVOICE_URL, json=payload, timeout=10)
        except Exception as e:
            log.warning(f"[send_invoice] Failed to mark sent: {e}")

        send_whatsapp_text(NADINE_WA, f"✅ Invoice sent to {client_name}")
        log.info(f"[invoices_router] Invoice sent → {client_name}")
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[invoices_router] send_invoice_to_client error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 5️⃣  EDIT LINK ENDPOINT
# ─────────────────────────────────────────────────────────────
@bp.route("/edit", methods=["POST"])
def edit_invoice():
    """Triggered manually or via callback."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "")
        month_spec = data.get("month_spec", "this month")
        sheet_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"

        msg = (
            f"✏️ To edit *{client_name}'s* invoice for {month_spec}, "
            f"open the Invoices tab:\n{sheet_link}\n\n"
            "Make changes and set status = 'edited' when done."
        )
        send_whatsapp_text(NADINE_WA, msg)
        log.info(f"[invoices_router] Edit link sent for {client_name}")
        return jsonify({"ok": True, "link": sheet_link})
    except Exception as e:
        log.error(f"[invoices_router] edit_invoice error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────
@bp.route("/", methods=["GET"])
def health():
    """Basic health check for invoices blueprint."""
    return jsonify({
        "status": "ok",
        "service": "Invoices Router",
        "endpoints": [
            "/invoices/review",
            "/invoices/review-one",
            "/invoices/send",
            "/invoices/edit",
            "/invoices/callback"
        ]
    }), 200
