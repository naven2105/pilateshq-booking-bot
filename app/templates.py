# app/templates.py
"""
WhatsApp Template Senders
Keeps outbound messages consistent and compliant.
"""

import json
import logging
import requests
from .config import ACCESS_TOKEN, GRAPH_URL, TEMPLATE_LANG

def send_template(to_wa: str, template_name: str, components: list[dict]) -> dict:
    """
    Send a pre-approved WhatsApp template message.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": TEMPLATE_LANG},  # should be en_US
            "components": components,
        },
    }

    try:
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        resp = requests.post(GRAPH_URL, headers=headers, data=json.dumps(payload), timeout=20)
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:500]}
        result = {"status_code": resp.status_code, **body}
        if resp.status_code >= 400:
            logging.error("WhatsApp TEMPLATE API %s: %s", resp.status_code, result)
        else:
            logging.info("WhatsApp TEMPLATE API %s OK", resp.status_code)
        return result
    except Exception as e:
        logging.exception("WhatsApp TEMPLATE call failed")
        return {"status_code": -1, "error": str(e)}


# ─────────────────────────────────────────────
# Admin Templates
# ─────────────────────────────────────────────

def send_admin_hourly(to: str, next_hour: str, status: str):
    """Admin hourly update template (US version)"""
    return send_template(
        to,
        "admin_update_us",
        [{"type": "body", "parameters": [
            {"type": "text", "text": next_hour},
            {"type": "text", "text": status},
        ]}],
    )

def send_admin_daily(to: str, total: str, schedule: str):
    """Admin 20h00 daily recap template (US version)"""
    return send_template(
        to,
        "admin_20h00_us",
        [{"type": "body", "parameters": [
            {"type": "text", "text": total},
            {"type": "text", "text": schedule},
        ]}],
    )

def send_admin_cancel_all(to: str, date: str, reason: str):
    """Admin cancel-all template (US version)"""
    return send_template(
        to,
        "admin_cancel_all_sessions_us",
        [{"type": "body", "parameters": [
            {"type": "text", "text": date},
            {"type": "text", "text": reason},
        ]}],
    )

# ─────────────────────────────────────────────
# Client Templates
# ─────────────────────────────────────────────

def send_client_tomorrow(to: str, time_str: str):
    """Client D-1 reminder (US version)"""
    return send_template(
        to,
        "client_session_tomorrow_us",
        [{"type": "body", "parameters": [
            {"type": "text", "text": time_str},
        ]}],
    )

def send_client_next_hour(to: str, time_str: str):
    """Client 1h-before reminder (US version)"""
    return send_template(
        to,
        "client_session_next_hour_us",
        [{"type": "body", "parameters": [
            {"type": "text", "text": time_str},
        ]}],
    )

def send_client_weekly(to: str, schedule: str):
    """Sunday weekly preview (US version)"""
    return send_template(
        to,
        "client_weekly_schedule_us",
        [{"type": "body", "parameters": [
            {"type": "text", "text": schedule},
        ]}],
    )
