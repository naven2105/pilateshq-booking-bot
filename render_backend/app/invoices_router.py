"""
invoices_router.py – Phase 17B (Unified Invoices + Payments + Health)
────────────────────────────────────────────────────────────
Handles all invoice and payment automation for PilatesHQ.

✅ Includes:
 • /invoices/send            → Dual Email + WhatsApp delivery
 • /invoices/resend          → Regenerate invoice PDF
 • /invoices/mark-paid       → Manual payment log
 • /invoices/log-payment     → Free-text or structured log
 • /invoices/view/<token>    → Secure PDF viewer
 • /invoices/health & /invoices/ → Service health check
────────────────────────────────────────────────────────────
"""

import os, io, time, re, logging, requests
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from .utils import send_safe_message
from .tokens import generate_invoice_token, verify_invoice_token

# ─────────────────────────────────────────────────────────────
bp = Blueprint("invoices_bp", __name__)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")

TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_ALERT = "client_generic_alert_us"
TPL_PAYMENT_LOGGED = "payment_logged_admin_us"

STATIC_DIR = os.path.join(os.path.dirname(__file__), "../static")
LOGO_PATH = os.path.join(STATIC_DIR, "pilateshq_logo.png")

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def flatten_message(text: str) -> str:
    if not text:
        return ""
    clean = text.replace("\n", " ").replace("\t", " ")
    while "  " in clean:
        clean = clean.replace("  ", " ")
    return clean.strip()

def _post_to_gas(payload: dict, retries: int = 2) -> dict:
    for attempt in range(retries + 1):
        try:
            if not GAS_INVOICE_URL:
                raise ValueError("Missing GAS_INVOICE_URL")
            r = requests.post(GAS_INVOICE_URL, json=payload, timeout=20)
            if r.ok:
                return r.json()
            log.warning(f"GAS HTTP {r.status_code}: {r.text}")
        except Exception as e:
            log.error(f"GAS POST failed ({attempt + 1}/{retries + 1}): {e}")
        time.sleep(2)
    return {"ok": False, "error": "GAS communication failed"}

# ─────────────────────────────────────────────────────────────
# Core endpoints (send / view / resend / mark-paid / log-payment)
# ─────────────────────────────────────────────────────────────
@bp.route("/send", methods=["POST"])
def send_invoice_dual():
    """Dual delivery → Email + WhatsApp (client)."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()
        wa_number = data.get("wa_number", "").strip() or NADINE_WA
        invoice_id = data.get("invoice_id") or f"INV-{int(time.time())}"

        if not client_name:
            return jsonify({"ok": False, "error": "Missing client_name"}), 400

        token = generate_invoice_token(client_name, invoice_id)
        view_url = f"{BASE_URL}/invoices/view/{token}"

        msg = flatten_message(f"🧾 PilatesHQ Invoice for *{client_name}*: {view_url} (expires in 48h)")
        send_safe_message(
            to=wa_number,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[msg],
            label="invoice_dual_send"
        )

        email_result = _post_to_gas({
            "action": "send_invoice_email",
            "sheet_id": SHEET_ID,
            "client_name": client_name
        })
        email_status = "Sent" if email_result.get("ok") else f"Failed: {email_result.get('error')}"

        _post_to_gas({
            "action": "append_log_event",
            "sheet_id": SHEET_ID,
            "event": "INVOICE_DUAL",
            "message": f"{client_name} | Email={email_status}"
        })

        return jsonify({
            "ok": True,
            "client_name": client_name,
            "invoice_id": invoice_id,
            "email_status": email_status,
            "link": view_url
        })

    except Exception as e:
        log.exception("send_invoice_dual error")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[flatten_message(f"❌ send_invoice_dual error: {e}")],
            label="invoice_dual_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/view/<token>", methods=["GET"])
def view_invoice(token):
    """Secure PDF viewer."""
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

    pdf.save()
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{client_name.replace(' ', '_')}_{invoice_id}.pdf"
    )

# other routes omitted for brevity ...

# ─────────────────────────────────────────────────────────────
# Health routes
# ─────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
@bp.route("/", methods=["GET"])
def health():
    """Basic router health check."""
    return jsonify({
        "status": "ok",
        "service": "invoices_router",
        "endpoints": [
            "/invoices/send",
            "/invoices/resend",
            "/invoices/view/<token>",
            "/invoices/mark-paid",
            "/invoices/log-payment",
            "/invoices/health"
        ]
    }), 200
