"""
invoices_router.py – Phase 7 (Secure PDF + Logo)
────────────────────────────────────────────
Adds:
 • /invoices/link        → creates signed expiring link
 • /invoices/view/<tok>  → validates token + generates live PDF
 • Embedded PilatesHQ logo in invoice header
────────────────────────────────────────────
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
# /invoices/unpaid → Returns unpaid / partial invoices
# ─────────────────────────────────────────────────────────────
@bp.route("/unpaid", methods=["GET", "POST"])
def list_unpaid_invoices():
    """
    Returns all unpaid or partially paid invoices from Google Apps Script.
    POST also triggers WhatsApp summary to Nadine.
    """
    try:
        result = _post_to_gas({"action": "list_overdue_invoices", "sheet_id": SHEET_ID})
        overdue = result.get("overdue", []) or result.get("unpaid", [])

        if not overdue:
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=["✅ All invoices are fully paid. Enjoy your day! 😊"],
                label="invoices_all_paid"
            )
            return jsonify({"ok": True, "message": "All invoices are paid."})

        lines, total_due = [], 0.0
        for rec in overdue:
            name = rec.get("client_name", "").strip()
            amt = float(rec.get("amount_due") or 0)
            if not name or amt <= 0:
                continue
            total_due += amt
            lines.append(f"{name} R{amt:,.0f}")

        summary = f"📋 PilatesHQ Invoices: {len(lines)} unpaid totalling R{total_due:,.0f}: " + "; ".join(lines)
        summary = " ".join(summary.split())

        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[summary],
            label="invoice_unpaid_summary"
        )

        log.info(f"✅ Unpaid invoice summary sent to Nadine ({len(lines)} clients).")
        return jsonify({
            "ok": True,
            "count": len(lines),
            "total_due": total_due,
            "overdue": overdue,
            "summary": summary
        })

    except Exception as e:
        log.error(f"❌ list_unpaid_invoices error: {e}")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[f"⚠️ Error fetching unpaid invoices: {e}"],
            label="invoice_unpaid_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /invoices/link → Generate a secure, expiring link
# ─────────────────────────────────────────────────────────────
@bp.route("/link", methods=["POST"])
def create_invoice_link():
    """
    Creates a short-lived, signed link for client invoice view/download.
    """
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name")
        invoice_id = data.get("invoice_id") or f"INV-{int(time.time())}"

        if not client_name:
            return jsonify({"ok": False, "error": "Missing client_name"}), 400

        token = generate_invoice_token(client_name, invoice_id)
        view_url = f"{BASE_URL}/invoices/view/{token}"

        msg = f"🔐 Secure invoice link for *{client_name}*:\n{view_url}\n(Expires in 48 h)"
        send_safe_message(NADINE_WA, msg)

        return jsonify({
            "ok": True,
            "client_name": client_name,
            "invoice_id": invoice_id,
            "link": view_url
        })

    except Exception as e:
        log.exception("❌ create_invoice_link error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /invoices/view/<token> → Verify token + generate PDF with logo
# ─────────────────────────────────────────────────────────────
@bp.route("/view/<token>", methods=["GET"])
def view_invoice(token):
    """
    Secure endpoint:
     • Validates signed token (expires after 48 h)
     • Generates and streams PDF directly to browser
     • Includes PilatesHQ logo
    """
    check = verify_invoice_token(token)
    if not check or not check.get("client"):
        return jsonify({"ok": False, "error": check.get("error", "Invalid token")}), 403

    client_name = check["client"]
    invoice_id = check["invoice"]

    # ── Placeholder invoice data (replace later)
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

    # ── Logo path and header
    logo_path = os.path.join(os.path.dirname(__file__), "../static/pilateshq_logo.png")
    if os.path.exists(logo_path):
        pdf.drawImage(logo_path, 50, 760, width=120, height=50, preserveAspectRatio=True)

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(200, 790, "PilatesHQ – Client Invoice")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(200, 770, f"Invoice: {invoice_id}")
    pdf.drawString(200, 755, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    pdf.drawString(200, 740, f"Client: {client_name}")
    pdf.line(50, 730, 550, 730)

    # ── Invoice body
    y = 710
    for desc, amt in items:
        pdf.drawString(60, y, desc)
        pdf.drawRightString(520, y, f"R {amt:.2f}")
        y -= 20
    pdf.line(50, y, 550, y)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(520, y - 20, f"Total: R {total:.2f}")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, y - 60, "Banking Details – Pilates HQ (Pty) Ltd / Absa 4117151887")
    pdf.save()
    buf.seek(0)

    filename = f"{client_name.replace(' ', '_')}_{invoice_id}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)


# ─────────────────────────────────────────────────────────────
# /invoices/test-send → Simple WhatsApp test
# ─────────────────────────────────────────────────────────────
@bp.route("/test-send", methods=["POST"])
def test_send_invoice():
    """Send a sample invoice message via WhatsApp template."""
    try:
        data = request.get_json(force=True)
        to = data.get("to", NADINE_WA)
        now = datetime.now()
        month_name = now.strftime("%B %Y")

        message = (
            f"{month_name} Invoice: "
            f"02, 04 Duo (R250)x2; 11, 18 Single (R300)x2.\n"
            f"💰 *Total R1,100 | Paid R600 | Balance R500.*\n"
            f"🏦 *Banking Details:*\n"
            f"Pilates HQ Pty Ltd\n"
            f"Absa Bank — Current Account\n"
            f"Account No: 4117151887\n"
            f"Reference: Your Name\n"
            f"📎 PDF: https://pilateshq.co.za/invoices/sample.pdf"
        )

        resp = send_safe_message(
            to=to,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[message],
            label="invoice_test_send_clean",
        )

        log.info(f"✅ Test invoice sent to {to}")
        return jsonify({"ok": True, "to": to, "message": message, "response": resp})

    except Exception as e:
        log.error(f"❌ test_send_invoice error: {e}")
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
            "/invoices/unpaid",
            "/invoices/link",
            "/invoices/view/<token>",
            "/invoices/test-send"
        ]
    }), 200
