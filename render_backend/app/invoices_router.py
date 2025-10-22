"""
invoices_router.py – Phase 9 (Dual-Channel Invoice Delivery, Final)
────────────────────────────────────────────────────────────
Adds:
 • Email (must succeed) + WhatsApp dual-send endpoint
 • Faster retry, success logging to Google Apps Script
 • Optional client WhatsApp number input
────────────────────────────────────────────────────────────
"""

import os, io, time, logging, requests
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from .utils import send_safe_message
from .tokens import generate_invoice_token, verify_invoice_token

bp = Blueprint("invoices_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ──────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")
TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_ALERT = "client_generic_alert_us"

STATIC_DIR = os.path.join(os.path.dirname(__file__), "../static")
LOGO_PATH = os.path.join(STATIC_DIR, "pilateshq_logo.png")


# ─────────────────────────────────────────────────────────────
# Utility: Unified Apps Script POST
# ─────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict) -> dict:
    try:
        if not GAS_INVOICE_URL:
            raise ValueError("Missing GAS_INVOICE_URL")
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=15)
        if not r.ok:
            log.error(f"GAS {r.status_code}: {r.text}")
            return {"ok": False, "error": f"GAS {r.status_code}"}
        return r.json()
    except Exception as e:
        log.error(f"GAS POST failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# /invoices/send → Email + WhatsApp Dual Delivery
# ─────────────────────────────────────────────────────────────
@bp.route("/send", methods=["POST"])
def send_invoice_dual():
    """Unified dual delivery – Email (mandatory) + WhatsApp."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()
        wa_number = data.get("wa_number", "").strip() or NADINE_WA
        invoice_id = data.get("invoice_id") or f"INV-{int(time.time())}"
        if not client_name:
            return jsonify({"ok": False, "error": "Missing client_name"}), 400

        # ── 1️⃣ Generate secure invoice link
        token = generate_invoice_token(client_name, invoice_id)
        view_url = f"{BASE_URL}/invoices/view/{token}"

        # ── 2️⃣ WhatsApp (non-blocking)
        try:
            msg = f"🧾 PilatesHQ Invoice for *{client_name}*: {view_url} (expires in 48 h)"
            send_safe_message(
                to=wa_number,
                is_template=True,
                template_name=TPL_CLIENT_ALERT,
                variables=[msg],
                label="invoice_dual_send"
            )
            wa_status = "Sent"
        except Exception as e:
            wa_status = f"Failed: {e}"
            log.error(f"WhatsApp send failed: {e}")

        # ── 3️⃣ Email (must succeed)
        email_payload = {"action": "send_invoice_email", "sheet_id": SHEET_ID, "client_name": client_name}
        email_result = _post_to_gas(email_payload)
        email_status = "Sent" if email_result.get("ok") else f"Failed: {email_result.get('error')}"

        # short retry (5 s)
        if not email_result.get("ok"):
            time.sleep(5)
            retry = _post_to_gas(email_payload)
            if retry.get("ok"):
                email_status = "Sent (Retry)"
            else:
                email_status = f"Failed (Retry): {retry.get('error')}"

        # ── 4️⃣ Log summary to Apps Script
        _post_to_gas({
            "action": "append_log_event",
            "sheet_id": SHEET_ID,
            "event": "INVOICE_DUAL",
            "message": f"{client_name} | Email={email_status} | WhatsApp={wa_status}"
        })

        # Notify Nadine only if email failed
        if "Failed" in email_status:
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=[f"⚠️ Invoice email failed for {client_name}: {email_status}"],
                label="invoice_email_failure"
            )

        return jsonify({
            "ok": True,
            "client_name": client_name,
            "invoice_id": invoice_id,
            "email_status": email_status,
            "whatsapp_status": wa_status,
            "link": view_url
        })

    except Exception as e:
        log.exception("send_invoice_dual error")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[f"❌ send_invoice_dual error: {e}"],
            label="invoice_dual_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /invoices/view/<token> → PDF Generator
# ─────────────────────────────────────────────────────────────
@bp.route("/view/<token>", methods=["GET"])
def view_invoice(token):
    check = verify_invoice_token(token)
    if not check or not check.get("client"):
        return jsonify({"ok": False, "error": "Invalid token"}), 403

    client_name = check["client"]
    invoice_id = check["invoice"]

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"{client_name} Invoice {invoice_id}")

    try:
        if os.path.exists(LOGO_PATH):
            pdf.drawImage(LOGO_PATH, 50, 760, width=100, height=50)
    except Exception as e:
        log.warning(f"Logo draw failed: {e}")

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(200, 790, "PilatesHQ – Client Invoice")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(200, 770, f"Invoice: {invoice_id}")
    pdf.drawString(200, 755, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    pdf.drawString(200, 740, f"Client: {client_name}")
    pdf.line(50, 730, 550, 730)

    y = 710
    items = [("02 Oct 2025 – Duo Session", 250), ("04 Oct 2025 – Duo Session", 250),
             ("11 Oct 2025 – Single Session", 300), ("18 Oct 2025 – Single Session", 300)]
    for desc, amt in items:
        pdf.drawString(60, y, desc)
        pdf.drawRightString(520, y, f"R {amt:.2f}")
        y -= 20

    pdf.line(50, y, 550, y)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(520, y - 20, f"Total: R {sum(i[1] for i in items):.2f}")

    y -= 60
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, y, "Banking Details:")
    for line in [
        "Pilates HQ (Pty) Ltd (Reg 2024/737238/07)",
        "Bank: ABSA",
        "Account: 4117151887"
    ]:
        y -= 15
        pdf.drawString(70, y, line)

    pdf.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=f"{client_name.replace(' ', '_')}_{invoice_id}.pdf")


# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────
@bp.route("", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Invoices Router",
        "endpoints": ["/invoices/send", "/invoices/view/<token>"]
    }), 200
