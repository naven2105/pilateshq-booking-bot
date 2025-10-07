# app/admin_flow.py
"""
Handles WhatsApp Flow submissions (e.g. client registration form).
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import safe_execute, send_whatsapp_text, normalize_wa

log = logging.getLogger(__name__)


def handle_flow_reply(msg: dict, from_wa: str):
    """Process a submitted WhatsApp Flow (e.g. new client registration)."""
    interactive = msg.get("interactive", {})
    flow_reply = interactive.get("flow_reply", {})
    responses = flow_reply.get("responses", {})

    log.info(f"[ADMIN_FLOW] Flow reply received from {from_wa}: {responses}")

    name = responses.get("Client Name")
    mobile = normalize_wa(responses.get("Mobile"))
    dob = responses.get("DOB")  # keep as text for now

    if not name or not mobile:
        log.warning("[ADMIN_FLOW] Missing required fields in flow reply")
        safe_execute(
            send_whatsapp_text,
            from_wa,
            "⚠ Could not process client form. Missing name or mobile.",
            label="flow_missing_fields",
        )
        return

    # Insert or update client
    with get_session() as s:
        s.execute(
            text("""
                INSERT INTO clients (name, wa_number, phone, birthday)
                VALUES (:n, :wa, :wa, :dob)
                ON CONFLICT (wa_number) DO UPDATE
                SET name=:n, birthday=:dob
            """),
            {"n": name, "wa": mobile, "dob": dob},
        )

    # Confirm to Nadine
    safe_execute(
        send_whatsapp_text,
        from_wa,
        f"✅ Client {name} ({mobile}) added via registration form.",
        label="flow_client_add",
    )

    # Optional: welcome message to client
    safe_execute(
        send_whatsapp_text,
        mobile,
        f"Hi {name}, welcome to PilatesHQ! 💜 Nadine will reach out to you soon.",
        label="flow_client_welcome",
    )
