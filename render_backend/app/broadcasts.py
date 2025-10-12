# app/broadcasts.py
"""
broadcasts.py
────────────────────────────────────────────
Handles studio-wide broadcast messages.
Supports:
  - Direct broadcast (list of numbers)
  - Sheet-driven broadcast (marketing / announcements)
"""

import logging
import requests
from . import utils
from .config import TEMPLATE_LANG

log = logging.getLogger(__name__)

GOOGLE_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbzXQgwxZZDisjHRs78yQeG7xsDNynSLLKcAV57fn1mflZa1dtCKdNvK-0YpkqNtyJiBqQ/exec"  # ⚙️ Replace with your deployed URL


# ─────────────────────────────────────────────────────────────
# 1️⃣ Direct Broadcast
# ─────────────────────────────────────────────────────────────
def send_broadcast(to_numbers: list[str], message: str) -> int:
    """
    Send a general broadcast (marketing / updates) using admin_update_us template.
    Args:
      to_numbers: list of WA numbers (27...)
      message: the {{1}} variable for the template
    Returns count of successful sends
    """
    if not to_numbers or not message:
        log.warning("[broadcast] Skipped empty broadcast (no recipients or message).")
        return 0

    sent = 0
    for to in to_numbers:
        try:
            resp = utils.send_whatsapp_template(
                to,
                "admin_update_us",  # ✅ Marketing template
                TEMPLATE_LANG,
                [message],
            )
            ok = resp.get("ok", False)
            log.info("[broadcast] to=%s msg=%s status=%s ok=%s",
                     to, message, resp.get("status_code"), ok)
            if ok:
                sent += 1
        except Exception as e:
            log.exception("[broadcast] Error sending to %s: %s", to, e)

    return sent


# ─────────────────────────────────────────────────────────────
# 2️⃣ Sheet-Driven Broadcast
# ─────────────────────────────────────────────────────────────
def send_broadcast_from_sheet(sheet_name: str = "Broadcasts") -> dict:
    """
    Reads a Google Sheet with two columns: name, wa_number, and optional message.
    Sends each entry the specified message (or a default).
    Returns a summary dict with sent/failed counts.
    """
    try:
        res = requests.get(f"{GOOGLE_WEB_APP_URL}?action=get_sheet&sheet={sheet_name}", timeout=15)
        if res.status_code != 200:
            log.error("[broadcast_sheet] Failed to fetch sheet (%s): %s", sheet_name, res.text)
            return {"ok": False, "error": "fetch_failed"}

        data = res.json()
        rows = data.get("rows", [])
        if not rows:
            log.warning("[broadcast_sheet] No data rows in sheet '%s'.", sheet_name)
            return {"ok": False, "sent": 0, "failed": 0}

        sent = 0
        failed = 0

        for r in rows:
            name = (r.get("name") or "").strip()
            wa = (r.get("wa_number") or "").strip()
            msg = (r.get("message") or "Hi! PilatesHQ has an update for you. 💜").strip()

            if not wa:
                log.warning("[broadcast_sheet] Skipped row (no WA): %s", name)
                failed += 1
                continue

            full_msg = msg.replace("{name}", name or "there")
            try:
                resp = utils.send_whatsapp_template(
                    wa, "admin_update_us", TEMPLATE_LANG, [full_msg]
                )
                ok = resp.get("ok", False)
                if ok:
                    sent += 1
                else:
                    failed += 1
                log.info("[broadcast_sheet] to=%s (%s) ok=%s", wa, name, ok)
            except Exception as e:
                failed += 1
                log.exception("[broadcast_sheet] Error sending to %s: %s", wa, e)

        summary = {"ok": True, "sent": sent, "failed": failed, "total": len(rows)}
        log.info("[broadcast_sheet] Summary: %s", summary)
        return summary

    except Exception as e:
        log.exception("[broadcast_sheet] Fatal error: %s", e)
        return {"ok": False, "error": str(e)}
