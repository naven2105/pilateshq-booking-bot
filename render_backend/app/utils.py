# render_backend/app/utils.py
"""
utils.py
────────────────────────────────────────────
Utility functions for the PilatesHQ WhatsApp Bot backend.

Includes:
 - send_whatsapp_template(): Meta Cloud API template sender
 - send_whatsapp_text(): plain text message sender
 - safe_execute(): error-safe wrapper for API calls
 - normalize_wa(): normalise WhatsApp numbers (e.g., 073 → 2773)
 - normalize_dob() / format_dob_display(): date helpers
────────────────────────────────────────────
"""

import os
import logging
import requests
import time
from datetime import datetime

log = logging.getLogger(__name__)

# ── Environment variables ───────────────────────────────────────
META_BASE_URL = "https://graph.facebook.com/v19.0"
META_PHONE_ID = os.getenv("META_PHONE_ID", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
DEFAULT_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# ─────────────────────────────────────────────────────────────
# WhatsApp number normaliser
# ─────────────────────────────────────────────────────────────
def normalize_wa(num: str) -> str:
    """Convert local SA numbers (e.g., 073...) to 27-prefix international format."""
    if not num:
        return ""
    s = str(num).strip().replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if s.startswith("0"):
        s = "27" + s[1:]
    return s


# ─────────────────────────────────────────────────────────────
# DOB utilities
# ─────────────────────────────────────────────────────────────
def normalize_dob(dob: str | None) -> str | None:
    """Normalise DOB text to YYYY-MM-DD format."""
    if not dob:
        return None
    dob = dob.strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%d %B", "%d %b"):
        try:
            dt = datetime.strptime(dob, fmt)
            # Replace missing year with current year
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    log.warning(f"[DOB] Could not parse {dob!r}")
    return None


def format_dob_display(dob_norm: str | None) -> str:
    """Display DOB nicely (DD-MMM or DD-MMM-YYYY)."""
    if not dob_norm:
        return "N/A"
    try:
        dt = datetime.strptime(dob_norm, "%Y-%m-%d")
        return dt.strftime("%d-%b" if dt.year == datetime.now().year else "%d-%b-%Y")
    except Exception:
        return "N/A"


# ─────────────────────────────────────────────────────────────
# Safe execution wrapper
# ─────────────────────────────────────────────────────────────
def safe_execute(label, func, *args, **kwargs):
    """Run an operation safely, logging errors instead of breaking execution."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        log.error(f"❌ {label} failed → {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Send WhatsApp Template Message
# ─────────────────────────────────────────────────────────────
def send_whatsapp_template(to: str, name: str, lang: str = DEFAULT_LANG, variables=None):
    """
    Send a pre-approved WhatsApp template message.
    Args:
        to: recipient phone number (string)
        name: template name (string)
        lang: language code (default: en_US)
        variables: list of string replacements for {{1}}, {{2}}, etc.
    """
    if not META_PHONE_ID or not META_ACCESS_TOKEN:
        log.warning("⚠️ Meta credentials missing, cannot send message.")
        return {"ok": False, "error": "missing credentials"}

    url = f"{META_BASE_URL}/{META_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": lang},
        },
    }

    if variables:
        data["template"]["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in variables],
        }]

    log.info(f"📤 Sending WhatsApp template → {to} ({name}) vars={variables}")

    try:
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        result = resp.json() if resp.text else {}
        if resp.status_code >= 400:
            log.error(f"❌ WhatsApp API error {resp.status_code}: {resp.text}")
            return {"ok": False, "status_code": resp.status_code, "error": resp.text}
        else:
            log.info(f"✅ WhatsApp message sent to {to} ({name}) → {resp.status_code}")
            return {"ok": True, "status_code": resp.status_code, "response": result}
    except Exception as e:
        log.error(f"❌ WhatsApp template send failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Send Free-Text Message
# ─────────────────────────────────────────────────────────────
def send_whatsapp_text(to: str, text: str):
    """Send a plain WhatsApp message (non-template)."""
    if not META_PHONE_ID or not META_ACCESS_TOKEN:
        log.warning("⚠️ Meta credentials missing.")
        return {"ok": False, "error": "missing credentials"}

    url = f"{META_BASE_URL}/{META_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalize_wa(to),
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    log.info(f"💬 Sending WhatsApp text → {to}: {text}")

    try:
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        result = resp.json() if resp.text else {}
        if resp.status_code >= 400:
            log.error(f"❌ WhatsApp text error {resp.status_code}: {resp.text}")
            return {"ok": False, "status_code": resp.status_code, "error": resp.text}
        else:
            log.info(f"✅ WhatsApp text sent to {to}")
            return {"ok": True, "status_code": resp.status_code, "response": result}
    except Exception as e:
        log.error(f"❌ WhatsApp text send failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Rate-limit safe send helper
# ─────────────────────────────────────────────────────────────
def send_with_delay(messages, delay=1.0):
    """
    Send multiple messages with spacing to avoid Meta rate limits.
    Args:
        messages: list of dicts, each with keys {to, name, vars}
        delay: seconds between sends
    """
    for msg in messages:
        safe_execute(
            f"Send to {msg.get('to')}",
            send_whatsapp_template,
            msg.get("to"),
            msg.get("name"),
            DEFAULT_LANG,
            msg.get("vars", []),
        )
        time.sleep(delay)

# ─────────────────────────────────────────────────────────────
# Reliable Webhook Poster with Retries
# ─────────────────────────────────────────────────────────────
def post_with_retry(url: str, payload: dict, retries: int = 3, delay: float = 2.0):
    """
    POST to a webhook with automatic retries and backoff.
    Used for critical actions (e.g., attendance close).
    """
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.ok:
                log.info(f"✅ [RETRY OK] {url} ({attempt}/{retries}) → {resp.status_code}")
                return resp
            log.warning(f"⚠️ [RETRY WARN] {url} attempt {attempt}/{retries} → {resp.status_code}")
        except Exception as e:
            log.warning(f"⚠️ [RETRY ERR] {url} attempt {attempt}/{retries} → {e}")
        time.sleep(delay * attempt)
    log.error(f"❌ [RETRY FAIL] All attempts failed for {url}")
    return None

# ─────────────────────────────────────────────────────────────
# HYBRID MESSAGE ROUTER (Final Production Version)
# ─────────────────────────────────────────────────────────────
def send_safe_message(
    to: str,
    message: str = "",
    *,
    label: str = "auto",
    is_template: bool = False,
    template_name: str = None,
    variables: list | None = None,
):
    """
    Smart WhatsApp message router.
    Handles Meta 24-hour re-engagement rules automatically.

    - Timer-based jobs → always use approved template
    - Admin/client replies → send free text if session open
    - If Meta returns error 131047, fallback to template delivery
    """
    try:
        # ─── Use template immediately for timed/system messages ───
        if is_template and template_name:
            log.info(f"[SAFE MSG] Template {template_name} → {to}")
            return send_whatsapp_template(to, template_name, TEMPLATE_LANG, variables or [])

        # ─── Otherwise, try free text ───
        log.info(f"[SAFE MSG] Free text → {to}")
        resp = send_whatsapp_text(to, message)
        resp_json = resp if isinstance(resp, dict) else {}

        # ─── Check for 24h session expiry ───
        if "131047" in json.dumps(resp_json) or "Re-engagement" in json.dumps(resp_json):
            log.warning(f"[SAFE MSG] 24h window closed for {to}. Re-sending via template.")
            tmpl = template_name or "admin_generic_alert_us"
            vars_ = variables or [message]
            return send_whatsapp_template(to, tmpl, TEMPLATE_LANG, vars_)

        # ─── Normal success path ───
        if resp_json.get("messages"):
            msg_id = resp_json["messages"][0].get("id")
            log.info(f"[SAFE MSG] Delivered {label} → {to} | {msg_id}")
        else:
            log.debug(f"[SAFE MSG] {to} response: {resp_json}")

        return resp_json

    except Exception as e:
        log.error(f"[send_safe_message] {label} :: {e}")
        return {"ok": False, "error": str(e)}
