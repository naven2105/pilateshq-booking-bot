import re
from flask import url_for
from .settings import ADMIN_NUMBER
from .invoices import generate_invoice_whatsapp

def handle_invoice_command(from_number: str, message: str) -> str | None:
    """
    Process admin 'invoice' commands.
    - "invoice Sept" → monthly report
    - "invoice Lily Sept" → short WhatsApp invoice (same as client gets)
    """
    if from_number != ADMIN_NUMBER:
        return None

    m = re.match(r"^invoice\s+(.+)$", message.strip(), flags=re.I)
    if not m:
        return None

    args = m.group(1).strip().split(maxsplit=1)

    if len(args) == 1:
        # Only month provided → monthly report
        month_spec = args[0]
        report_url = url_for("diag_monthly_report_html", month=month_spec, _external=True)
        csv_url = url_for("diag_monthly_report_csv", month=month_spec, _external=True)
        return (
            f"📑 PilatesHQ Monthly Report ({month_spec})\n"
            f"• View report: {report_url}\n"
            f"• Download CSV: {csv_url}"
        )
    else:
        # Client + month provided → short WhatsApp invoice
        client_name, month_spec = args[0], args[1]
        base_url = url_for("webhook", _external=True).rstrip("/webhook")  # get app base URL
        invoice_msg = generate_invoice_whatsapp(client_name, month_spec, base_url)
        return invoice_msg
