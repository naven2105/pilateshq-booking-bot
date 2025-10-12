# app/diag.py
"""
diag.py
────────────────────────────────────────────
Diagnostics, PDF previews, and test utilities
for admin validation and troubleshooting.
"""

import logging
from flask import Blueprint, request, jsonify, Response
from .utils import _send_to_meta, send_whatsapp_text, normalize_wa
from .invoices import generate_invoice_pdf, generate_invoice_whatsapp
from .reports import generate_monthly_report_pdf  # ✅ Add missing import

log = logging.getLogger(__name__)
diag_bp = Blueprint("diag", __name__)

# ──────────────────────────────────────────────
# Invoice PDF preview
# ──────────────────────────────────────────────
@diag_bp.route("/diag/invoice-pdf", methods=["GET"])
def diag_invoice_pdf():
    """Return generated invoice PDF inline (for browser or WhatsApp link)."""
    client = request.args.get("client", "Unknown Client")
    month = request.args.get("month", "this month")
    pdf_bytes = generate_invoice_pdf(client, month)
    safe_name = client.replace(" ", "_").replace("/", "_")
    filename = f"Invoice_{safe_name}_{month}.pdf".replace(" ", "_")
    log.info(f"[DIAG] Invoice PDF generated for {client} ({month})")

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

# ──────────────────────────────────────────────
# Monthly report PDF preview
# ──────────────────────────────────────────────
@diag_bp.route("/diag/monthly-report-pdf", methods=["GET"])
def diag_monthly_report_pdf():
    """Return monthly admin report as PDF."""
    month = request.args.get("month", "this month")
    pdf_bytes = generate_monthly_report_pdf(month)
    filename = f"Monthly_Report_{month}.pdf".replace(" ", "_")
    log.info(f"[DIAG] Monthly report PDF generated for {month}")

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

# ──────────────────────────────────────────────
# WhatsApp Invoice Test (Admin-only)
# ──────────────────────────────────────────────
@diag_bp.route("/diag/send-invoice-test", methods=["GET"])
def diag_send_invoice_test():
    """
    Sends a WhatsApp test invoice message to Nadine (for review).
    Useful for previewing the improved WhatsApp invoice layout.
    """
    from os import getenv
    NADINE_WA = getenv("NADINE_WA", "")
    if not NADINE_WA:
        return jsonify({"error": "NADINE_WA not configured"}), 400

    month = request.args.get("month", "this month")
    client_name = "Test Client"

    msg = generate_invoice_whatsapp(client_name, month, getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com"))
    send_whatsapp_text(NADINE_WA, msg)

    log.info(f"[DIAG] Test WhatsApp invoice sent to Nadine ({NADINE_WA})")
    return jsonify({"ok": True, "message_sent_to": NADINE_WA, "month": month})
