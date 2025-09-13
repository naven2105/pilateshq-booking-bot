# app/templates.py
from __future__ import annotations
import logging
import json
import requests
from typing import Dict, Any, List

from .config import ACCESS_TOKEN, GRAPH_URL

def send_whatsapp_template(
    to_wa: str,
    template_name: str,
    lang: str,
    components: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Send a WhatsApp template message.
    Args:
        to_wa: Normalized WhatsApp number (e.g. "2762...").
        template_name: Name of the approved template (e.g. "session_weekly").
        lang: Language code (e.g. "en", "en_ZA").
        components: WhatsApp template components (body, header, buttons).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": components or []
        },
    }

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(GRAPH_URL, headers=headers, data=json.dumps(payload), timeout=20)
        status = resp.status_code
        body = {}
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {"raw_text": (resp.text or "").strip()[:500]}
        result = {"status_code": status, **body}
        if status >= 400:
            logging.error("WhatsApp API template %s: %s", status, result)
        else:
            logging.info("WhatsApp API template %s OK", status)
        return result
    except Exception as e:
        logging.exception("WhatsApp API template call failed")
        return {"status_code": -1, "error": str(e)}
