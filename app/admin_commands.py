import re
from flask import url_for
from .settings import ADMIN_NUMBER
from .invoices import generate_invoice_text
from .invoices_workflow import generate_payments_report

# ────────────────────────────────────────────────
# Handle "invoice ..." admin command
# ────────────────────────────────────────────────

def handle_invoice_command(from_number: str, message: str) -> str | None:
    """
    Process admin 'invoice' commands.
    Examples:
      - "invoice Sept" → monthly report
      - "invoice Lily Sept" → single client invoice
    Returns a text message (or None if not an invoice command).
    """
    if from_number != ADMIN_NUMBER:
        return None  # only Nadine can use this

    m = re.match(r"^invoice\s+(.+)$", message.strip(), flags=re.I)
    if not m:
        return None

    args = m.group(1).strip().split(maxsplit=1)
    if len(args) == 1:
        # only month provided → monthly report
        month_spec = args[0]
        report_url = url_for("diag_monthly_report_html", month=month_spec, _external=True)
        csv_url = url_for("diag_monthly_report_csv", month=month_spec, _external=True)
        return (
            f"📑 PilatesHQ Monthly Report ({month_spec})\n"
            f"• View report: {report_url}\n"
            f"• Download CSV: {csv_url}"
        )
    else:
        # client + month provided → individual invoice
        client_name, month_spec = args[0], args[1]
        invoice_text = generate_invoice_text(client_name, month_spec)
        html_url = url_for("diag_invoice_html", client=client_name, month=month_spec, _external=True)
        csv_url = url_for("diag_invoice_csv", client=client_name, month=month_spec, _external=True)
        return (
            f"{invoice_text}\n\n"
            f"🔗 Download options:\n"
            f"• HTML: {html_url}\n"
            f"• CSV: {csv_url}"
        )
