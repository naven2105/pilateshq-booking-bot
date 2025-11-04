"""
invoices_router.py – Phase 17 (Unified Invoices + Payments + Health)
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
# /invoices/send
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

# ─────────────────────────────────────────────────────────────
# /invoices/view/<token>
# ─────────────────────────────────────────────────────────────
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

    # Example placeholder line items
    y = 710
    items = [
        ("02 Oct 2025 – Duo Session", 250),
        ("04 Oct 2025 – Duo Session", 250),
        ("11 Oct 2025 – Single Session", 300),
        ("18 Oct 2025 – Single Session", 300)
    ]
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
        "Account: 4117151887",
        "Payments due on or before the 25th each month.",
        "Send POP to Nadine (084 313 1635)."
    ]:
        y -= 15
        pdf.drawString(70, y, line)

    pdf.save()
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{client_name.replace(' ', '_')}_{invoice_id}.pdf"
    )

# ─────────────────────────────────────────────────────────────
# /invoices/resend
# ─────────────────────────────────────────────────────────────
@bp.route("/resend", methods=["POST"])
def resend_invoice():
    """Regenerate and resend invoice PDF."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()
        month = data.get("month", "").strip()
        wa_number = data.get("wa_number", "").strip() or NADINE_WA

        if not client_name or not month:
            return jsonify({"ok": False, "error": "Missing client_name or month"}), 400

        payload = {
            "action": "generate_invoice_pdf",
            "sheet_id": SHEET_ID,
            "client_name": client_name,
            "month": month
        }
        resp = _post_to_gas(payload)
        if not resp.get("ok"):
            raise Exception(resp.get("error", "PDF generation failed"))

        pdf_link = resp.get("pdf_link")
        msg = flatten_message(
            f"📄 PilatesHQ Invoice for {month} is ready for {client_name}. View here: {pdf_link}"
        )
        send_safe_message(
            to=wa_number,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[msg],
            label="invoice_resend"
        )
        return jsonify({"ok": True, "pdf_link": pdf_link})

    except Exception as e:
        log.exception("resend_invoice error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# /invoices/mark-paid
# ─────────────────────────────────────────────────────────────
@bp.route("/mark-paid", methods=["POST"])
def mark_paid():
    """Structured payment logging (Nadine manual input)."""
    try:
        data = request.get_json(force=True)
        client = data.get("client_name", "").strip()
        amount = data.get("amount")
        date = data.get("date") or datetime.now().strftime("%Y-%m-%d")
        note = data.get("note", "")

        if not client or not amount:
            return jsonify({"ok": False, "error": "Missing client_name or amount"}), 400

        append_result = _post_to_gas({
            "action": "appendPayment_",
            "client_name": client,
            "amount": amount,
            "date": date,
            "note": note
        })
        if not append_result.get("ok"):
            raise Exception(append_result.get("error", "appendPayment_ failed"))

        match_result = _post_to_gas({"action": "autoMatchInvoice_", "client_name": client})
        status = match_result.get("status", "Pending")

        msg = flatten_message(
            f"✅ Payment logged for *{client}*\nAmount: R{amount}\nStatus: {status}\nNote: {note or '—'}"
        )
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_PAYMENT_LOGGED,
            variables=[msg],
            label="payment_mark_paid"
        )

        return jsonify({"ok": True, "client_name": client, "status": status})
    except Exception as e:
        log.exception("mark_paid error")
        send_safe_message(NADINE_WA, f"⚠️ Payment logging failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# /invoices/log-payment (free text)
# ─────────────────────────────────────────────────────────────
@bp.route("/log-payment", methods=["POST"])
def log_payment():
    """Handles free-text or NLP payment logs."""
    try:
        data = request.get_json(force=True)
        text = (data.get("text") or "").strip()
        client_name = (data.get("client_name") or "").strip()
        amount = data.get("amount")
        date = data.get("date")

        if text and (not client_name or not amount):
            m = re.match(r"(.+?)\s+paid\s+R?(\d+(?:\.\d{1,2})?)", text, re.I)
            if m:
                client_name = client_name or m.group(1).strip().title()
                amount = amount or float(m.group(2))

        if not client_name or not amount:
            return jsonify({"ok": False, "error": "Missing client_name or amount"}), 400

        payload = {
            "action": "appendPayment_",
            "client_name": client_name,
            "amount": amount,
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "note": "NLP payment log"
        }
        resp = _post_to_gas(payload)
        msg = f"✅ {client_name} payment logged (R{amount})"
        send_safe_message(NADINE_WA, msg)
        return jsonify(resp)
    except Exception as e:
        log.exception("log_payment error")
        return jsonify({"ok": False, "error": str(e)}), 500

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
