import logging

logger = logging.getLogger(__name__)

def _send_to_meta(payload: dict) -> tuple:
    """
    Internal: POST a payload to Meta WhatsApp Cloud API.
    Returns (ok: bool, status_code: int, response: dict).
    """
    url = WHATSAPP_API_URL.format(phone_number_id=PHONE_NUMBER_ID)
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if not resp.ok:
            logger.error("[MetaSendError] status=%s body=%s payload=%s", resp.status_code, resp.text, payload)
        return resp.ok, resp.status_code, resp.json()
    except Exception as e:
        logger.exception("[MetaSendException] payload=%s", payload)
        return False, 500, {"error": str(e)}
