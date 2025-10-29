# render_backend/app/admin_nudge.py
"""
admin_nudge.py – Phase 20 (Guest Logic Revision)
────────────────────────────────────────────────────────────
Removed legacy lead alerts and WhatsApp template usage.
Guests contacting the bot are now redirected automatically
to Nadine (handled in router_client.py).
────────────────────────────────────────────────────────────
"""

import os
import logging

log = logging.getLogger(__name__)

# ── Environment Configuration ─────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# ── Helper: Validate phone number ─────────────────────────────
def _validate_wa_number(num: str) -> bool:
    """Ensure WhatsApp number looks valid (digits only, 10+ chars)."""
    return num and num.isdigit() and len(num) >= 10

# ── Guest lead handling (now passive) ─────────────────────────
def notify_new_lead(name: str, wa_number: str):
    """
    Previously: sent admin_new_lead_alert to Nadine.
    Now: purely logs the event (no WhatsApp message sent).
    """
    clean_name = (name or "Unknown").strip()
    clean_number = (wa_number or "Unknown").strip()
    log.info(f"👋 Guest reached bot: {clean_name} ({clean_number}) — redirected to Nadine.")
    # No WhatsApp template messages are sent here anymore.
