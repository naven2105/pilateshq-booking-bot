"""
invoices_router.py – Phase 9 (Dual-Channel Invoice Delivery)
────────────────────────────────────────────────────────────
Adds:
 • Automatic email delivery via Google Apps Script (MailApp)
 • WhatsApp and Email channels decoupled (email always executes)
 • Detailed logging for both channels
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
TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_ALERT = "client_generic_alert_us"
BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")

# ── Static paths and assets ──────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "../static")
LOGO_FILENAME = "pilateshq_logo.png"
LOGO_PATH = os.path.normpath(os.path.join(STATIC_DIR, LOGO_FILENAME))

# ─────────────────────────────────────────────────────────────
# Utility: Unified Apps Script POST
# ─────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict) -> dict:
    """Safely post JSON payload to Google Apps Script endpoint."""
    try:
        if not GAS_INVOICE_URL:
            raise ValueError("Missing GAS_INVOICE_URL environment variable.")
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=15)
        if not r.ok:
            log.error(f"Apps Script HTTP {r.status_code}: {r.text}")
            return {"ok": False, "error": f"Apps Script HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        log.error(f"[invoices_router] GAS POST failed: {e}")
        return {"ok": False, "error": str(e)}

# ─────────────────────────────────────────────────────────────
# /invoices/send → Dual Delivery (WhatsApp + Email)
# ─────────────────────────────────────────────────────────────
@bp.route("/send", methods=["POST"])
def send_invoice_dual():
    """
    Dual delivery entrypoint.
    1️⃣ Generate secure invoice link
    2️⃣ Send via WhatsApp (non-blocking)
    3️⃣ Always trigger Apps Script email delivery (with one retry)
    """
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name")
        wa_number = data.get("wa_number", "")
        invoice_id = data.get("invoice_id") or f"INV-{int(time.time())}"

        if not client_name:
            return jsonify({"ok": False, "error": "Missing client_name"}), 400

        # ── Generate secure tokenised link
        token = generate_invoice_token(client_name, invoice_id)
        view_url = f"{BASE_URL}/invoices/view/{token}"

        # ── WhatsApp delivery (non-blocking)
        try:
            msg = f"🔐 PilatesHQ Invoice for *{client_name}*: {view_url} (48 h expiry)"
            send_safe_message(
                to=wa_number or NADINE_WA,
                is_template=True,
                template_name=TPL_CLIENT_ALERT,
                variables=[msg],
                label="invoice_dual_whatsapp"
            )
            wa_status = "Sent"
        except Exception as e:
            wa_status = f"Failed: {e}"
            log.error(f"WhatsApp send failed for {client_name}: {e}")

        # ── Email delivery (must always run, with retry)
        email_payload = {
            "action": "send_invoice_email",
            "sheet_id": SHEET_ID,
            "client_name": client_name
        }

        email_result = _post_to_gas(email_payload)
        email_status = "Sent" if email_result.get("ok") else f"Failed: {email_result.get('error')}"

        # 🔁 Retry once after 30 s if failed
        if not email_result.get("ok"):
            log.warning(f"Retrying email for {client_name} in 30 s …")
            time.sleep(30)
            retry_result = _post_to_gas(email_payload)
            if retry_result.get("ok"):
                email_status = "Sent (Retry Success)"
            else:
                email_status = f"Failed (After Retry): {retry_result.get('error')}"
                log.error(f"Email retry failed for {client_name}: {retry_result}")

        # ── Logging summary
        summary = (
            f"📤 Invoice delivery summary for {client_name}\n"
            f"• WhatsApp: {wa_status}\n"
            f"• Email: {email_status}"
        )
        log.info(summary)

        if "Failed" in email_status:
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=[f"⚠️ Invoice email failure for {client_name}: {email_status}"],
                label="invoice_email_failure"
            )

        return jsonify({
            "ok": True,
            "client_name": client_name,
            "invoice_id": invoice_id,
            "whatsapp_status": wa_status,
            "email_status": email_status,
            "link": view_url
        })

    except Exception as e:
        log.exception("❌ send_invoice_dual error")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[f"⚠️ Error sending dual invoice: {e}"],
            label="invoice_dual_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# /invoices/view/<token> → PDF Generator (unchanged)
# ─────────────────────────────────────────────────────────────
@bp.route("/view/<token>", methods=["GET"])
def view_invoice(token):
    check = verify_invoice_token(token)
    if not check or not check.get("client"):
        return jsonify({"ok": False, "error": check.get("error", "Invalid token")}), 403

    client_name = check["client"]
    invoice_id = check["invoice"]
    client_mobile = "(+27 62 759 7357)"

    items = [
        ("02 Oct 2025 – Duo Session", 250),
        ("04 Oct 2025 – Duo Session", 250),
        ("11 Oct 2025 – Single Session", 300),
        ("18 Oct 2025 – Single Session", 300),
    ]
    total = sum(i[1] for i in items)

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"{client_name} Invoice {invoice_id}")

    try:
        if os.path.exists(LOGO_PATH):
            pdf.drawImage(LOGO_PATH, 50, 760, width=100, height=50, preserveAspectRatio=True)
    except Exception as e:
        log.warning(f"Logo load failed: {e}")

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(200, 790, "PilatesHQ – Client Invoice")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(200, 770, f"Invoice: {invoice_id}")
    pdf.drawString(200, 755, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    pdf.drawString(200, 740, f"Client: {client_name} {client_mobile}")
    pdf.line(50, 730, 550, 730)

    y = 710
    for desc, amt in items:
        pdf.drawString(60, y, desc)
        pdf.drawRightString(520, y, f"R {amt:.2f}")
        y -= 20
    pdf.line(50, y, 550, y)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(520, y - 20, f"Total: R {total:.2f}")

    pdf.setFont("Helvetica", 10)
    y -= 70
    pdf.drawString(50, y, "Banking Details:")
    y -= 15
    pdf.drawString(70, y, "Pilates HQ (Pty) Ltd (Reg 2024/737238/07)")
    y -= 15
    pdf.drawString(70, y, "Bank: ABSA")
    y -= 15
    pdf.drawString(70, y, "Current Account: 4117151887")

    pdf.save()
    buf.seek(0)

    filename = f"{client_name.replace(' ', '_')}_{invoice_id}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)

# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────
@bp.route("", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Invoices Router",
        "endpoints": [
            "/invoices/send",
            "/invoices/view/<token>",
            "/invoices/unpaid"
        ]
    }), 200

# ─────────────────────────────────────────────────────────────
# Log logo path on startup
# ─────────────────────────────────────────────────────────────
if os.path.exists(LOGO_PATH):
    log.info(f"✅ Logo found at {LOGO_PATH}")
else:
    log.warning(f"⚠️ Logo missing at {LOGO_PATH}")
