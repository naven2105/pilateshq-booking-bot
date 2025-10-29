"""
utils.py – PilatesHQ WhatsApp Bot Utilities (Phase 18.3)
────────────────────────────────────────────────────────────
Full file version – all outgoing WhatsApp messages (template + text)
are now single-line and sanitised (no newlines, tabs, or >4 spaces).

Includes:
 • clean_text() sanitiser
 • send_whatsapp_template() & send_whatsapp_text() with auto-clean
 • send_safe_message() router with automatic template fallback
 • safe_execute(), retry logic, DOB helpers, number normalisation
────────────────────────────────────────────────────────────
"""

import os
import re
import logging
import requests
import json
import time
from datetime import datetime

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────
META_BASE_URL = "https://graph.facebook.com/v19.0"
META_PHONE_ID = os.getenv("META_PHONE_ID", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "en_US")

# ─────────────────────────────────────────────────────────────
# Sanitiser
# ─────────────────────────────────────────────────────────────
def clean_text(t: str) -> str:
    """Remove newlines, tabs, and long spaces for WhatsApp parameters."""
    return re.sub(r"\s{2,}", " ", re.sub(r"[\n\r\t]+", " ", str(t or "").strip()))

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
# Send WhatsApp Template Message (Sanitised)
# ─────────────────────────────────────────────────────────────
def send_whatsapp_template(to: str, name: str, lang: str = DEFAULT_LANG, variables=None):
    """Send a pre-approved WhatsApp template message (sanitised)."""
    if not META_PHONE_ID or not META_ACCESS_TOKEN:
        log.warning("⚠️ Meta credentials missing, cannot send message.")
        return {"ok": False, "error": "missing credentials"}

    url = f"{META_BASE_URL}/{META_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    safe_vars = [clean_text(v) for v in (variables or [])]

    data = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": lang},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(v)} for v in safe_vars],
                }
            ],
        },
    }

    log.info(f"📤 Sending WhatsApp template → {to} ({name}) vars={safe_vars}")

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
# Send Free-Text Message (Sanitised)
# ─────────────────────────────────────────────────────────────
def send_whatsapp_text(to: str, text: str):
    """Send a plain WhatsApp message (sanitised)."""
    if not META_PHONE_ID or not META_ACCESS_TOKEN:
        log.warning("⚠️ Meta credentials missing.")
        return {"ok": False, "error": "missing credentials"}

    text = clean_text(text)

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
    """Send multiple messages with spacing to avoid Meta rate limits."""
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
    """POST to a webhook with automatic retries and backoff."""
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
# HYBRID MESSAGE ROUTER (Production) – Sanitised
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
    All messages are cleaned of newlines, tabs, and excessive spaces.
    """
    try:
        message = clean_text(message)
        variables = [clean_text(v) for v in (variables or [])]

        # Use template immediately for system messages
        if is_template and template_name:
            log.info(f"[SAFE MSG] Template {template_name} → {to}")
            return send_whatsapp_template(to, template_name, DEFAULT_LANG, variables)

        # Otherwise, free text path
        log.info(f"[SAFE MSG] Free text → {to}")
        resp = send_whatsapp_text(to, message)

        try:
            resp_json = resp if isinstance(resp, dict) else (resp.json() if hasattr(resp, "json") else {})
        except Exception:
            resp_json = {}

        # Detect expired 24h window
        if "131047" in json.dumps(resp_json) or "Re-engagement" in json.dumps(resp_json):
            log.warning(f"[SAFE MSG] 24h window closed for {to}. Re-sending via template.")
            tmpl = template_name or "admin_generic_alert_us"
            vars_ = variables or [message]
            return send_whatsapp_template(to, tmpl, DEFAULT_LANG, vars_)

        if isinstance(resp_json, dict) and resp_json.get("messages"):
            msg_id = resp_json["messages"][0].get("id")
            log.info(f"[SAFE MSG] Delivered {label} → {to} | {msg_id}")
        else:
            log.debug(f"[SAFE MSG] {to} response: {resp_json}")

        return resp_json

    except Exception as e:
        log.error(f"[send_safe_message] {label} :: {e}")
        return {"ok": False, "error": str(e)}
