"""
admin_nudge.py
────────────────────────────────────────────
Simplified version (no database).
Sends admin notifications to Nadine via WhatsApp template messages.
"""

import os
import logging
from render_backend.app.utils import send_whatsapp_template, sanitize_param

log = logging.getLogger(__name__)

# ── Environment Configuration ─────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
ADMIN_NEW_LEAD_TEMPLATE = "admin_new_lead_alert"

# ── Helper: Validate phone number ─────────────────────────────
def _validate_wa_number(num: str) -> bool:
    return num and num.isdigit() and len(num) >= 10


# ── Notify Nadine of a new lead ───────────────────────────────
def notify_new_lead(name: str, wa_number: str):
    """
    Send a WhatsApp template notification to Nadine
    whenever a new lead or enquiry is received.
    """
    if not NADINE_WA:
        log.warning("⚠️ NADINE_WA not set — cannot send admin alerts.")
        return

    if not _validate_wa_number(NADINE_WA):
        log.error(f"Invalid NADINE_WA: {NADINE_WA}")
        return

    clean_name = sanitize_param(name or "Unknown")
    clean_number = sanitize_param(wa_number or "Unknown")

    log.info(f"📢 Sending admin new lead alert → {clean_name} ({clean_number})")

    result = send_whatsapp_template(
        to=NADINE_WA,
        name=ADMIN_NEW_LEAD_TEMPLATE,
        lang=TEMPLATE_LANG,
        variables=[clean_name, clean_number],
    )

    if result.get("ok"):
        log.info("✅ Admin notification sent successfully.")
    else:
        log.error(f"❌ Failed to send admin alert: {result}")
