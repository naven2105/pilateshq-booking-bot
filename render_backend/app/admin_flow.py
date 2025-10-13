# app/admin_flow.py
"""
admin_flow.py
────────────────────────────────────────────
Handles WhatsApp Flow submissions (e.g. client registration form).
Integrates directly with Google Sheets via webhook.
"""

import logging
from .utils import safe_execute, send_whatsapp_text, normalize_wa, post_to_webhook
from .config import WEBHOOK_BASE

log = logging.getLogger(__name__)


def handle_flow_reply(msg: dict, from_wa: str):
    """Process a submitted WhatsApp Flow (new client registration form)."""
    interactive = msg.get("interactive", {})
    flow_reply = interactive.get("flow_reply", {})
    responses = flow_reply.get("responses", {})

    log.info(f"[ADMIN_FLOW] Flow reply received from {from_wa}: {responses}")

    # Extract responses (field names depend on your Meta form setup)
    name = (responses.get("Client Name") or "").strip()
    mobile = normalize_wa(responses.get("Mobile") or "")
    dob = (responses.get("DOB") or "").strip()  # free text accepted

    if not name or not mobile:
        log.warning("[ADMIN_FLOW] Missing required fields in flow reply")
        safe_execute(
            send_whatsapp_text,
            from_wa,
            "⚠ Could not process client form. Missing name or mobile.",
            label="flow_missing_fields",
        )
        return

    # 🔹 Push new client to Google Sheets via webhook
    try:
        payload = {
            "action": "add_client",
            "name": name,
            "phone": mobile,
            "status": "active",
            "notes": f"Registered via WhatsApp Flow ({from_wa})",
        }

        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)
        log.info(f"[ADMIN_FLOW] Added client via Sheets → {res}")

        # ✅ Confirm to Nadine (the admin submitting form)
        safe_execute(
            send_whatsapp_text,
            from_wa,
            f"✅ Client {name} ({mobile}) added via registration form.",
            label="flow_client_add",
        )

        # 💬 Welcome message to client
        safe_execute(
            send_whatsapp_text,
            mobile,
            f"Hi {name}, welcome to PilatesHQ! 💜 Nadine will reach out to you soon.",
            label="flow_client_welcome",
        )

    except Exception as e:
        log.exception("❌ Error adding client via WhatsApp Flow")
        safe_execute(
            send_whatsapp_text,
            from_wa,
            f"⚠ Something went wrong adding {name}. Please retry or add manually.",
            label="flow_error",
        )
