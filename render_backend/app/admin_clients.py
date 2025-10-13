#app/admin_clients.py
"""
admin_clients.py
────────────────
Handles client management:
 - Add clients
 - Convert leads
 - Attendance updates (sick, no-show, cancel next session)
 - Deactivate clients
"""

import logging
from .utils import send_whatsapp_text, normalize_wa, safe_execute, post_to_webhook
from .config import WEBHOOK_BASE
from . import admin_nudge

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Sheets-based client lookup & creation
# ─────────────────────────────────────────────────────────────
def _find_or_create_client(name: str, wa_number: str | None = None):
    """
    Look up a client by name from Google Sheets.
    If not found and wa_number provided, create a new one via webhook.
    Returns (client_id, wa_number, existed)
    """
    try:
        wa_number = normalize_wa(wa_number) if wa_number else None
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_clients"})
        clients = res.get("clients", []) if isinstance(res, dict) else []

        # Try to find existing by name or number
        for c in clients:
            cname = (c.get("name") or "").strip().lower()
            cnum = normalize_wa(c.get("phone") or "")
            if cname == name.lower() or (wa_number and cnum == wa_number):
                log.info(f"[CLIENT EXISTS] name={name}, wa={wa_number}")
                return c.get("client_id"), cnum, True

        # Create if not found
        if wa_number:
            post_to_webhook(f"{WEBHOOK_BASE}/sheets", {
                "action": "add_client",
                "name": name,
                "phone": wa_number,
                "status": "active",
                "notes": "Auto-added via admin command"
            })
            log.info(f"[CLIENT CREATED] name={name}, wa={wa_number}")
            return None, wa_number, False

        log.warning(f"[CLIENT NOT FOUND] {name}")
        return None, None, False

    except Exception as e:
        log.error(f"❌ Error in _find_or_create_client: {e}")
        return None, None, False


# ─────────────────────────────────────────────────────────────
# Main handler for admin client actions
# ─────────────────────────────────────────────────────────────
def handle_client_command(parsed: dict, wa: str):
    """Route parsed client/admin commands (Sheets integration)."""

    intent = parsed.get("intent")
    log.info(f"[ADMIN CLIENT] parsed={parsed}")

    # ── Add Client ───────────────────────────────────────────
    if intent == "add_client":
        name = parsed.get("name", "").strip()
        number = parsed.get("number", "").replace("+", "").strip()

        if not name or not number:
            safe_execute(send_whatsapp_text, wa,
                "⚠ Missing name or number. Usage: 'Add client Alice 0821234567'",
                label="add_client_missing"
            )
            return

        # Normalise SA number format
        if number.startswith("0"):
            number = "27" + number[1:]

        cid, wnum, existed = _find_or_create_client(name, number)
        if existed:
            safe_execute(send_whatsapp_text, wa,
                f"ℹ Client '{name}' already exists with number {wnum}.",
                label="add_client_exists"
            )
        else:
            safe_execute(send_whatsapp_text, wa,
                f"✅ Client '{name}' added with number {wnum}.",
                label="add_client_ok"
            )
            # Send welcome message
            safe_execute(send_whatsapp_text, wnum,
                f"💜 Hi {name}, you’ve been added as a PilatesHQ client. "
                f"Nadine will confirm your bookings with you soon!",
                label="client_welcome"
            )
        return

    # ── Cancel Next ───────────────────────────────────────────
    if intent == "cancel_next":
        from .admin_bookings import cancel_next_booking
        cancel_next_booking(parsed.get("name"), wa)
        return

    # ── Sick Today ────────────────────────────────────────────
    if intent == "off_sick_today":
        from .admin_bookings import mark_today_status
        mark_today_status(parsed.get("name"), "sick", wa)
        return

    # ── No-show ───────────────────────────────────────────────
    if intent == "no_show_today":
        from .admin_bookings import mark_today_status
        mark_today_status(parsed.get("name"), "no_show", wa)
        return

    # ── Deactivation ──────────────────────────────────────────
    if intent == "deactivate":
        admin_nudge.request_deactivate(parsed.get("name"), wa)
        return

    if intent == "confirm_deactivate":
        admin_nudge.confirm_deactivate(parsed.get("name"), wa)
        return

    if intent == "cancel":
        safe_execute(send_whatsapp_text, wa,
            "❌ Deactivation cancelled. No changes made.",
            label="deactivate_cancel"
        )
        return
