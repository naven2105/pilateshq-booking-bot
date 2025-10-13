#app/admin_invoices.py
"""
admin_invoices.py
─────────────────
Admin-facing invoice & balance management.
Now integrated with Google Sheets (Sessions, Clients, Packages).
"""

import logging
from datetime import datetime, timedelta
from .utils import send_whatsapp_text, safe_execute, normalize_wa, post_to_webhook
from .config import WEBHOOK_BASE

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _normalize_month(month: str | None) -> tuple[str, str]:
    """Return month label ('September 2025') and key ('2025-09')."""
    today = datetime.today()

    if not month or month.lower() in {"this month", "current"}:
        label = today.strftime("%B %Y")
        key = today.strftime("%Y-%m")
        return label, key

    if month.lower() == "last month":
        prev = today.replace(day=1) - timedelta(days=1)
        label = prev.strftime("%B %Y")
        key = prev.strftime("%Y-%m")
        return label, key

    try:
        dt = datetime.strptime(month, "%B %Y")
        label = dt.strftime("%B %Y")
        key = dt.strftime("%Y-%m")
        return label, key
    except Exception:
        label = today.strftime("%B %Y")
        key = today.strftime("%Y-%m")
        return label, key


def _find_client(name: str):
    """Look up a client by name via Google Sheets."""
    try:
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_clients"})
        clients = res.get("clients", []) if isinstance(res, dict) else []

        for c in clients:
            cname = (c.get("name") or "").strip().lower()
            if cname == name.lower():
                wa = normalize_wa(c.get("phone") or "")
                return c.get("client_id", None), wa
        return None, None
    except Exception as e:
        log.error(f"❌ Error fetching clients from Sheets: {e}")
        return None, None


# ───────────────────────────────────────────────
# Admin invoice actions
# ───────────────────────────────────────────────
def send_invoice_admin(client_name: str, wa_number: str | None = None, month: str | None = None, admin_wa: str | None = None):
    """
    Admin requests invoice for a client → simulated PDF link (no DB).
    Gathers session data from Google Sheets.
    """
    cid, wa = _find_client(client_name)
    if not cid:
        safe_execute(
            send_whatsapp_text,
            admin_wa or wa_number,
            f"⚠ No client found named '{client_name}'.",
            label="admin_invoice_fail",
        )
        return

    label, key = _normalize_month(month)

    # Fetch sessions from Sheets
    try:
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res.get("sessions", []) if isinstance(res, dict) else []
        client_sessions = [
            s for s in sessions
            if (normalize_wa(s.get("wa_number", "")) == wa)
            and (s.get("session_date", "").startswith(key))
            and (s.get("status", "").lower() == "confirmed")
        ]
        count = len(client_sessions)
    except Exception as e:
        log.error(f"❌ Error fetching sessions: {e}")
        count = 0

    # ── Generate response
    if count == 0:
        msg = (
            f"💜 PilatesHQ — Invoice for {client_name} ({label})\n"
            f"No sessions booked in this period."
        )
        safe_execute(send_whatsapp_text, admin_wa or wa_number, msg, label="admin_invoice_empty")
        return

    # Simulate a PDF link for now
    pdf_url = (
        f"https://pilateshq-booking-bot.onrender.com/invoice?"
        f"client={wa}&month={label.replace(' ', '%20')}"
    )
    msg = (
        f"📑 Invoice for {client_name} — {label}\n\n"
        f"🧘 Sessions: {count}\n"
        f"🔗 Download (preview): {pdf_url}"
    )
    safe_execute(send_whatsapp_text, admin_wa or wa_number, msg, label="admin_invoice_ok")


def show_balance_admin(client_name: str, wa_number: str | None = None, admin_wa: str | None = None):
    """
    Admin requests balance for a client.
    Uses the Packages sheet to check sessions remaining.
    """
    cid, wa = _find_client(client_name)
    if not cid:
        safe_execute(
            send_whatsapp_text,
            admin_wa or wa_number,
            f"⚠ No client found named '{client_name}'.",
            label="admin_balance_fail",
        )
        return

    try:
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_packages"})
        packages = res.get("packages", []) if isinstance(res, dict) else []

        # Look for the latest active package
        pkg = next(
            (p for p in reversed(packages)
             if (p.get("client_name", "").strip().lower() == client_name.lower())),
            None
        )

        if not pkg:
            msg = f"⚠ No active package found for {client_name}."
            safe_execute(send_whatsapp_text, admin_wa or wa_number, msg, label="admin_balance_none")
            return

        total = int(pkg.get("sessions_total", 0))
        used = int(pkg.get("sessions_used", 0))
        remaining = total - used

        msg = (
            f"💜 Balance for {client_name}\n"
            f"Total: {total}\nUsed: {used}\nRemaining: {remaining}"
        )
        safe_execute(send_whatsapp_text, admin_wa or wa_number, msg, label="admin_balance_ok")

    except Exception as e:
        log.error(f"❌ Error fetching packages from Sheets: {e}")
        safe_execute(
            send_whatsapp_text,
            admin_wa or wa_number,
            f"⚠ Could not retrieve balance for {client_name}.",
            label="admin_balance_fail",
        )
