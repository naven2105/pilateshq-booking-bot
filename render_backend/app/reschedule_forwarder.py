#app/reschedule_forwarder.py
"""
Handles forwarding of RESCHEDULE messages to Google Apps Script.
"""

import os
import requests
from flask import current_app

# The Apps Script Web App URL (you will create this next)
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL")

def forward_reschedule(client_name: str, phone: str):
    """Notify Google Apps Script when a client asks to reschedule."""
    if not APPS_SCRIPT_URL:
        current_app.logger.warning("APPS_SCRIPT_URL not set")
        return
    try:
        payload = {"name": client_name, "phone": phone}
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=10)
        current_app.logger.info(
            f"📤 Forwarded RESCHEDULE for {client_name} ({phone}) → {res.status_code}"
        )
    except Exception as e:
        current_app.logger.error(f"❌ Failed to forward RESCHEDULE: {e}")
