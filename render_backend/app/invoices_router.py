"""
invoices_router.py – Phase 12 (Final + Debug/Image Fix + Reissue helper)
────────────────────────────────────────────
Adds to Phase 12:
 • Temporary LOGO_PATH existence logging for deployment debug
 • ImageReader() + preserveAspectRatio to avoid invisible/stretched PNG
 • WhatsApp-safe text (no newlines/tabs in template variable)
 • Minimal /invoices/reissue to match your PowerShell test
────────────────────────────────────────────
"""

import os, io, time, logging, requests, re
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
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

STATIC_DIR = os.path.join(os.path.dirname(__file__), "../static")
LOGO_PATH = os.path.join(STATIC_DIR, "pilateshq_logo.png")


# ─────────────────────────────────────────────────────────────
# Utility: Unified Apps Script POST
# ─────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict) -> dict:
    try:
        if not GAS_INVOICE_URL:
            raise ValueError("Missing GAS_INVOICE_URL")
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=20)
        if not r.ok:
            log.error(f"GAS {r.status_code}: {r.text}")
            return {"ok": False, "error": f"GAS HTTP {r.status_code}"}
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

        # 1️⃣ Generate secure invoice link
        token = generate_invoice_token(client_name, invoice_id)
        view_url = f"{BASE_URL}/invoices/view/{token}"

        # 2️⃣ WhatsApp send (non-blocking)
        try:
            raw = f"🧾 PilatesHQ Invoice for *{client_name}*: {view_url} (expires in 48 h)"
            msg = re.sub(r'[\n\t]+', ' ', raw)              # no CR/LF in template vars
            msg = re.sub(r'\s{2,}', ' ', msg)
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
        email_payload = {"action": "send_invoice_email", "sheet_id": SHEET_ID, "client_name": client_name}
        email_result = _post_to_gas(email_payload)
        email_status = "Sent" if email_result.get("ok") else f"Failed: {email_result.get('error')}"

        # Retry once after short delay
        if not email_result.get("ok"):
            time.sleep(5)
            retry = _post_to_gas(email_payload)
            if retry.get("ok"):
                email_status = "Sent (Retry)"
            else:
                email_status = f"Failed (Retry): {retry.get('error')}"

        # 4️⃣ Log summary to Apps Script
        _post_to_gas({
            "action": "append_log_event",
            "sheet_id": SHEET_ID,
            "event": "INVOICE_DUAL",
            "message": f"{client_name} | Email={email_status} | WhatsApp={wa_status}"
        })

        # Notify Nadine if email failed
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
# /invoices/view/<token> → PDF Viewer  (with logo debug + ImageReader)
# ─────────────────────────────────────────────────────────────
@bp.route("/view/<token>", methods=["GET"])
def view_invoice(token):
    check = verify_invoice_token(token)
    if not check or not check.get("client"):
        return jsonify({"ok": False, "error": "Invalid token"}), 403

    client_name = check["client"]
    invoice_id = check["invoice"]

    # Debug: confirm path in container
    log.info(f"LOGO_PATH={LOGO_PATH}, exists={os.path.exists(LOGO_PATH)}")

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"{client_name} Invoice {invoice_id}")

    try:
        if os.path.exists(LOGO_PATH):
            img = ImageReader(LOGO_PATH)
            pdf.drawImage(
                img, 50, 760,
                width=100,              # keep your Phase-12 geometry
                preserveAspectRatio=True,
                anchor='nw',
                mask='auto'
            )
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
# /invoices/deliver → Generate + WhatsApp Delivery
# ─────────────────────────────────────────────────────────────
@bp.route("/deliver", methods=["POST"])
def deliver_invoice():
    """Generate invoice via GAS and deliver via WhatsApp."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()
        wa_number = data.get("wa_number", "").strip() or NADINE_WA

        if not client_name:
            return jsonify({"ok": False, "error": "Missing client_name"}), 400
        if not GAS_INVOICE_URL:
            return jsonify({"ok": False, "error": "Missing GAS_INVOICE_URL"}), 500

        # 1️⃣ Generate invoice via GAS
        log.info(f"Generating invoice for {client_name} via GAS...")
        r = requests.post(
            GAS_INVOICE_URL,
            json={"action": "generate_invoice_pdf", "client_name": client_name},
            timeout=20
        )

        try:
            resp = r.json()
        except Exception:
            log.error(f"Non-JSON GAS response: {r.text[:200]}")
            return jsonify({"ok": False, "error": "Invalid GAS response"}), 502

        if not resp.get("ok"):
            return jsonify({"ok": False, "error": resp.get("error", "GAS generation failed")}), 502

        pdf_link = resp.get("pdf_link")
        if not pdf_link:
            return jsonify({"ok": False, "error": "No pdf_link in response"}), 502

        # 2️⃣ WhatsApp message (newline-safe)
        raw = f"📄 PilatesHQ Invoice ready for {client_name}. View here: {pdf_link} (Available for 48 hours)"
        message = re.sub(r'[\n\t]+', ' ', raw)
        message = re.sub(r'\s{2,}', ' ', message)
        send_safe_message(
            to=wa_number,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[message],
            label="invoice_deliver"
        )
        log.info(f"Invoice successfully delivered to {client_name} via WhatsApp")

        return jsonify({"ok": True, "client_name": client_name, "pdf_link": pdf_link})

    except Exception as e:
        log.exception("deliver_invoice error")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[f"❌ deliver_invoice error: {e}"],
            label="invoice_deliver_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# NEW: Minimal /reissue to support your PowerShell test on Phase-12
# ─────────────────────────────────────────────────────────────
@bp.route("/reissue", methods=["POST"])
def reissue_invoice():
    """
    Body: {"client_name":"Mary Smith","month":"September 2025"}
    Generates a token bound to 'month' and returns a /view/<token> link.
    """
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name","").strip()
        month = data.get("month","").strip()
        if not client_name or not month:
            return jsonify({"ok":False,"error":"Missing client_name or month"}),400

        # For Phase-12, our viewer expects an 'invoice' field in the token.
        # We’ll encode month into the same slot so /view works unchanged.
        token = generate_invoice_token(client_name, month)  # token payload handled in tokens.py
        view_url = f"{BASE_URL}/invoices/view/{token}"

        # WhatsApp-safe info message to Nadine (optional)
        info = re.sub(r'\s{2,}', ' ', f"📄 Reissue prepared for {client_name} – {month}: {view_url}")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[info],
            label="invoice_reissue_phase12"
        )

        return jsonify({"ok":True,"client_name":client_name,"month":month,"link":view_url})
    except Exception as e:
        log.exception("reissue_invoice error (phase12)")
        return jsonify({"ok":False,"error":str(e)}),500


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
            "/invoices/deliver",
            "/invoices/reissue"
        ]
    }), 200
