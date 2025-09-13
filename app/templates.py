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
    Args:
        to_wa (str): Normalized WhatsApp number (27...).
        template_name (str): Template name (must exist in Meta Business Manager).
        components (list): Variables for the template.
    Returns:
        dict: API response with status_code and any JSON body.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": TEMPLATE_LANG},
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


def send_admin_hourly(to: str, next_hour: str, status: str):
    """Admin hourly update template"""
    return send_template(
        to,
        "admin_hourly_update",
        [{"type": "body", "parameters": [
            {"type": "text", "text": next_hour},
            {"type": "text", "text": status},
        ]}],
    )

def send_admin_daily(to: str, total: str, schedule: str):
    """Admin 20h00 daily recap template"""
    return send_template(
        to,
        "admin_20h00",
        [{"type": "body", "parameters": [
            {"type": "text", "text": total},
            {"type": "text", "text": schedule},
        ]}],
    )

def send_client_tomorrow(to: str, time_str: str):
    """Client D-1 reminder"""
    return send_template(
        to,
        "session_tomorrow",
        [{"type": "body", "parameters": [
            {"type": "text", "text": time_str},
        ]}],
    )

def send_client_next_hour(to: str, time_str: str):
    """Client 1h-before reminder"""
    return send_template(
        to,
        "session_next_hour",
        [{"type": "body", "parameters": [
            {"type": "text", "text": time_str},
        ]}],
    )

def send_client_weekly(to: str, schedule: str):
    """Sunday weekly preview"""
    return send_template(
        to,
        "session_weekly_preview",
        [{"type": "body", "parameters": [
            {"type": "text", "text": schedule},
        ]}],
    )
