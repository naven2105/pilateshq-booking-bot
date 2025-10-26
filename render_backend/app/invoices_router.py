"""
invoices_router.py – Phase 14 (Final)
────────────────────────────────────────────
Enhancements:
 • Adds /invoices/mark-paid endpoint for Payment Handling Automation
 • Integrates GAS appendPayment_() + autoMatchInvoice_()
 • Sends admin-only WhatsApp confirmations (payment_logged_admin_us)
 • Retains Resend Fix + Flattened Templates + Secure GAS Integration
────────────────────────────────────────────
"""
import os, io, time, logging, requests
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from .utils import send_safe_message
from .tokens import generate_invoice_token, verify_invoice_token

# ── Blueprint setup ─────────────────────────────────────────────
bp = Blueprint("invoices_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────────
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
# Utility: Message flattener
# ─────────────────────────────────────────────────────────────
def flatten_message(text: str) -> str:
    if not text:
        return ""
    clean = text.replace("\n", " ").replace("\t", " ")
    while "  " in clean:
        clean = clean.replace("  ", " ")
    return clean.strip()


# ─────────────────────────────────────────────────────────────
# Utility: Unified Apps Script POST with retry
# ─────────────────────────────────────────────────────────────
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

        # 1️⃣ Generate secure invoice link
        token = generate_invoice_token(client_name, invoice_id)
        view_url = f"{BASE_URL}/invoices/view/{token}"

        # 2️⃣ WhatsApp send
        try:
            msg = flatten_message(f"🧾 PilatesHQ Invoice for *{client_name}*: {view_url} (expires in 48h)")
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

        # 3️⃣ Email (must succeed)
        email_payload = {
            "action": "send_invoice_email",
            "sheet_id": SHEET_ID,
            "client_name": client_name
        }
        email_result = _post_to_gas(email_payload)
        email_status = "Sent" if email_result.get("ok") else f"Failed: {email_result.get('error')}"

        if not email_result.get("ok"):
            time.sleep(5)
            retry = _post_to_gas(email_payload)
            if retry.get("ok"):
                email_status = "Sent (Retry)"
            else:
                email_status = f"Failed (Retry): {retry.get('error')}"

        _post_to_gas({
            "action": "append_log_event",
            "sheet_id": SHEET_ID,
            "event": "INVOICE_DUAL",
            "message": f"{client_name} | Email={email_status} | WhatsApp={wa_status}"
        })

        if "Failed" in email_status:
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=[flatten_message(f"⚠️ Invoice email failed for {client_name}: {email_status}")],
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
            variables=[flatten_message(f"❌ send_invoice_dual error: {e}")],
            label="invoice_dual_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /invoices/view/<token> → PDF Viewer
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
        "Account: 4117151887"
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
# /invoices/resend → On-demand lite invoice regeneration
# ─────────────────────────────────────────────────────────────
@bp.route("/resend", methods=["POST"])
def resend_invoice():
    """
    Nadine’s on-demand resend from Invoices Sheet.
    Body: {"client_name":"Mary Smith","month":"October 2025"}
    """
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()
        month = data.get("month", "").strip()
        wa_number = data.get("wa_number", "").strip() or NADINE_WA

        if not client_name or not month:
            return jsonify({"ok": False, "error": "Missing client_name or month"}), 400
        if not GAS_INVOICE_URL:
            return jsonify({"ok": False, "error": "Missing GAS_INVOICE_URL"}), 500

        log.info(f"Resend invoice for {client_name} – {month}")
        payload = {
            "action": "generate_invoice_pdf",
            "sheet_id": SHEET_ID,
            "client_name": client_name,
            "month": month
        }
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=25)
        try:
            resp = r.json()
        except Exception:
            log.error(f"Non-JSON GAS response: {r.text[:200]}")
            return jsonify({"ok": False, "error": "Invalid GAS response"}), 502

        if not resp.get("ok"):
            err = resp.get("error", "GAS generation failed")
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=[flatten_message(f"⚠️ Unable to resend invoice for {client_name}: {err}")],
                label="invoice_resend_error"
            )
            return jsonify({"ok": False, "error": err}), 502

        pdf_link = resp.get("pdf_link")
        if not pdf_link:
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=[flatten_message(f"⚠️ No pdf_link returned for {client_name} – {month}")],
                label="invoice_resend_no_link"
            )
            return jsonify({"ok": False, "error": "Missing pdf_link"}), 502

        msg_text = flatten_message(
            f"📄 PilatesHQ Invoice for {month} is ready for {client_name}. "
            f"View here: {pdf_link}. Available for 48 hours."
        )

        send_safe_message(
            to=wa_number,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[msg_text],
            label="invoice_resend"
        )

        _post_to_gas({
            "action": "append_log_event",
            "sheet_id": SHEET_ID,
            "event": "INVOICE_RESEND",
            "message": f"{client_name} | {month} | resent via WhatsApp"
        })

        log.info(f"Invoice resent successfully to {client_name}")
        return jsonify({"ok": True, "client_name": client_name, "month": month, "pdf_link": pdf_link})

    except Exception as e:
        log.exception("resend_invoice error")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[flatten_message(f"❌ resend_invoice error: {e}")],
            label="invoice_resend_exception"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /invoices/review-summary → Notify unreviewed invoices count
# ─────────────────────────────────────────────────────────────
@bp.route("/review-summary", methods=["POST"])
def review_summary():
    """Nadine command: 'review invoices'."""
    try:
        log.info("🔎 Checking unreviewed invoices via GAS")
        r = requests.post(GAS_INVOICE_URL, json={"action": "count_unreviewed_invoices"}, timeout=20)
        resp = r.json() if r.ok else {}
        if not resp.get("ok"):
            err = resp.get("error", "GAS call failed")
            return jsonify({"ok": False, "error": err}), 502

        count = int(resp.get("count", 0))
        next_client = resp.get("next_client", "")
        next_month = resp.get("next_month", "")

        summary = flatten_message(f"📑 {count} invoice(s) pending review. Next draft: {next_client} – {next_month}.")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[summary],
            label="invoice_review_summary"
        )

        log.info(f"Invoice review summary sent → {summary}")
        return jsonify({"ok": True, "count": count, "next_client": next_client, "next_month": next_month})

    except Exception as e:
        log.exception("review_summary error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /invoices/mark-paid → Payment logging from Nadine
# ─────────────────────────────────────────────────────────────
@bp.route("/mark-paid", methods=["POST"])
def mark_paid():
    """
    Logs a received payment (POP notice from Nadine).
    Example:
      {"client_name":"Mary Smith","amount":600,"date":"2025-10-26","note":"POP received"}
    """
    try:
        data = request.get_json(force=True)
        client = data.get("client_name", "").strip()
        amount = data.get("amount")
        date = data.get("date") or datetime.now().strftime("%Y-%m-%d")
        note = data.get("note", "")

        if not client or not amount:
            return jsonify({"ok": False, "error": "Missing client_name or amount"}), 400

        log.info(f"🧾 Logging payment for {client}: R{amount} on {date}")

        # Step 1 – Append payment
        append_result = _post_to_gas({
            "action": "appendPayment_",
            "client_name": client,
            "amount": amount,
            "date": date,
            "note": note
        })
        if not append_result.get("ok"):
            raise Exception(append_result.get("error", "appendPayment_ failed"))

        # Step 2 – Auto-match invoice
        match_result = _post_to_gas({
            "action": "autoMatchInvoice_",
            "client_name": client
        })
        status = match_result.get("status", "Pending")

        # Step 3 – Private confirmation
        msg = flatten_message(
            f"✅ Payment logged for *{client}*\n"
            f"Amount: R{amount}\nStatus: {status}\nNote: {note or '—'}"
        )
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_PAYMENT_LOGGED,
            variables=[msg],
            label="payment_mark_paid"
        )

        _post_to_gas({
            "action": "append_log_event",
            "sheet_id": SHEET_ID,
            "event": "PAYMENT_LOG",
            "message": f"{client} | R{amount} | {status}"
        })

        return jsonify({"ok": True, "client_name": client, "status": status})

    except Exception as e:
        log.exception("mark_paid error")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[flatten_message(f"⚠️ Payment logging failed: {e}")],
            label="payment_mark_paid_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


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
            "/invoices/resend",
            "/invoices/review-summary",
            "/invoices/mark-paid"
        ]
    }), 200
