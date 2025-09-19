# app/broadcasts.py
import logging
from . import utils
from .config import TEMPLATE_LANG

log = logging.getLogger(__name__)

def send_broadcast(to_numbers: list[str], message: str) -> int:
    """
    Send a general broadcast (marketing / updates) using admin_update_us template.
    Args:
      to_numbers: list of WA numbers (27...)
      message: the {{1}} variable for the template
    Returns count of successful sends
    """
    sent = 0
    for to in to_numbers:
        resp = utils.send_whatsapp_template(
            to,
            "admin_update_us",  # ✅ Marketing template
            "en_US",            # we fixed on US English
            [message],          # {{1}} = message
        )
        ok = resp.get("ok", False)
        log.info("[broadcast] to=%s msg=%s status=%s ok=%s",
                 to, message, resp.get("status_code"), ok)
        if ok:
            sent += 1
    return sent
