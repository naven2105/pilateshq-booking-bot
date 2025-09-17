from flask import Blueprint, request, jsonify, url_for, Response
from .utils import (
    send_admin_20h00,
    send_client_session_next_hour,
    send_client_session_tomorrow,
    send_admin_cancel_all_sessions,
    send_client_weekly_schedule,
    send_admin_update,
    _send_to_meta,
)
from .invoices import (
    generate_invoice_text,
    generate_invoice_html,
    generate_monthly_report_csv,
    generate_monthly_report_html,
)

diag_bp = Blueprint("diag", __name__)

# ... (previous routes unchanged)

# ────────────────────────────────────────────────
# Monthly reports
# ────────────────────────────────────────────────

@diag_bp.route("/diag/send_monthly_report_html")
def diag_send_monthly_report_html():
    """
    Send Nadine a WhatsApp link to view the monthly report (HTML).
    Usage:
      /diag/send_monthly_report_html?to=27735534607&month=Sept%202025
    """
    to = request.args.get("to")
    month = request.args.get("month", "this month")

    report_url = url_for("diag_monthly_report_html", month=month, _external=True)
    message = f"📑 PilatesHQ Monthly Report ({month})\nClick here to view: {report_url}"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    ok, status, body = _send_to_meta(payload)
    return jsonify({"ok": ok, "status": status, "response": body, "preview": message})


@diag_bp.route("/diag/send_monthly_report_csv")
def diag_send_monthly_report_csv():
    """
    Send Nadine a WhatsApp link to download the monthly report (CSV).
    Usage:
      /diag/send_monthly_report_csv?to=27735534607&month=Sept%202025
    """
    to = request.args.get("to")
    month = request.args.get("month", "this month")

    report_url = url_for("diag_monthly_report_csv", month=month, _external=True)
    message = f"📊 PilatesHQ Monthly Report CSV ({month})\nDownload here: {report_url}"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    ok, status, body = _send_to_meta(payload)
    return jsonify({"ok": ok, "status": status, "response": body, "preview": message})


# ────────────────────────────────────────────────
# Browser previews for monthly reports
# ────────────────────────────────────────────────

@diag_bp.route("/diag/monthly-report-html")
def diag_monthly_report_html():
    month = request.args.get("month", "this month")
    html = generate_monthly_report_html(month)
    return html

@diag_bp.route("/diag/monthly-report-csv")
def diag_monthly_report_csv():
    month = request.args.get("month", "this month")
    csv_text = generate_monthly_report_csv(month)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=monthly_report_{month}.csv"}
    )
