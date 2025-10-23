"""
admin_adjustments.py
────────────────────
Handles Nadine’s natural-language admin actions for:
 • Changing a client’s session type
 • Applying invoice discounts (percent or fixed amount)
────────────────────
"""

import os
import requests
import logging
from .admin_nlp import parse_admin_command
from .settings import ADMIN_NUMBER
from .utils import send_safe_message

log = logging.getLogger(__name__)

GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
NADINE_WA = ADMIN_NUMBER


def handle_admin_adjustment(from_number: str, message: str) -> str | None:
    """
    Interpret Nadine’s WhatsApp commands and send them
    as structured API calls to the Google Apps Script layer.
    """
    if from_number != ADMIN_NUMBER:
        return None

    intent_data = parse_admin_command(message)
    if not intent_data:
        return None

    intent = intent_data.get("intent")

    # ── 1️⃣  Change session type ───────────────────────────────
    if intent == "update_session_type":
        payload = {
            "action": "update_session_type",
            "client_name": intent_data["name"],
            "session_date": intent_data["date"],
            "new_type": intent_data["new_type"],
        }
        log.info(f"[ADJ] Updating session → {payload}")
        res = _call_gas(payload)
        return _reply(res, f"✅ Updated {payload['client_name']}'s {payload['session_date']} session to {payload['new_type'].capitalize()}.")

    # ── 2️⃣  Apply percentage discount ─────────────────────────
    if intent == "apply_discount_percent":
        payload = {
            "action": "apply_discount",
            "client_name": intent_data["name"],
            "discount_type": "percent",
            "discount_value": intent_data["discount_value"],
        }
        log.info(f"[ADJ] Applying % discount → {payload}")
        res = _call_gas(payload)
        return _reply(res, f"✅ Applied {payload['discount_value']}% discount to {payload['client_name']}'s invoice.")

    # ── 3️⃣  Apply fixed-amount discount ───────────────────────
    if intent == "apply_discount_amount":
        payload = {
            "action": "apply_discount",
            "client_name": intent_data["name"],
            "discount_type": "amount",
            "discount_value": intent_data["discount_value"],
        }
        log.info(f"[ADJ] Applying fixed discount → {payload}")
        res = _call_gas(payload)
        return _reply(res, f"✅ Applied R{payload['discount_value']} discount to {payload['client_name']}'s invoice.")

    return None


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _call_gas(payload: dict) -> dict:
    """POST JSON payload to the configured GAS endpoint."""
    try:
        res = requests.post(GAS_INVOICE_URL, json=payload, timeout=30)
        return res.json() if res.text.strip() else {"ok": False, "error": "Empty response"}
    except Exception as e:
        log.exception("GAS call failed")
        return {"ok": False, "error": str(e)}


def _reply(res: dict, success_msg: str) -> str:
    """Return success or failure text for WhatsApp."""
    if res.get("ok"):
        send_safe_message(NADINE_WA, success_msg)
        return success_msg
    else:
        err = res.get("error", "Unknown error")
        msg = f"⚠️ Action failed: {err}"
        send_safe_message(NADINE_WA, msg)
        return msg
