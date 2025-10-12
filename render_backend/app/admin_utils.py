#app/admin_utils.py
"""
admin_utils.py
──────────────
Shared utilities for admin modules:
 - Client lookup and creation
 - DOB formatting
 - Hybrid fuzzy client matching (via Google Sheets)
 - Disambiguation helper
"""

import logging
from datetime import datetime
from difflib import get_close_matches
from .utils import send_whatsapp_text, safe_execute, post_to_webhook
from .config import WEBHOOK_BASE, SHEETS_API_URL

log = logging.getLogger(__name__)

CLIENTS_SHEET = "Clients"


# ─────────────────────────────────────────────────────────────
# Client Lookup / Creation
# ─────────────────────────────────────────────────────────────
def _find_or_create_client(name: str, wa_number: str | None = None):
    """
    Look up a client by name in the Google Sheet.
    If not found and wa_number is given, create a new record.
    Returns (client_id, wa_number, name, dob_day+month)
    """
    try:
        # ✅ Fetch client data from Apps Script (Clients sheet)
        payload = {"action": "get_clients"}
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)
        rows = res.get("clients", []) if isinstance(res, dict) else []

        # Search for exact match
        for r in rows:
            cname = (r.get("name") or "").strip()
            if cname.lower() == name.lower():
                return r.get("client_id"), r.get("phone"), cname, f"{r.get('dob_day','')}-{r.get('dob_month','')}"
    except Exception as e:
        log.warning(f"[Sheets] Failed to fetch clients: {e}")

    # Not found → create if number provided
    if wa_number:
        payload = {
            "action": "add_client",
            "name": name,
            "phone": wa_number,
            "dob_day": "",
            "dob_month": "",
            "status": "active",
            "notes": "Auto-added via admin command"
        }
        post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)
        log.info(f"[Sheets] Created new client {name} ({wa_number})")
        return None, wa_number, name, None

    return None, None, None, None


# ─────────────────────────────────────────────────────────────
# Format DOB
# ─────────────────────────────────────────────────────────────
def _format_dob(dob: str | None) -> str | None:
    """Format DOB as DD-MMM (ignore year)."""
    if not dob:
        return None
    try:
        dt = datetime.strptime(dob, "%Y-%m-%d")
        return dt.strftime("%d-%b")
    except Exception:
        return dob


# ─────────────────────────────────────────────────────────────
# Hybrid Client Matching (Fuzzy + Substring)
# ─────────────────────────────────────────────────────────────
def _find_client_matches(name: str):
    """Return list of possible client matches from Google Sheet."""
    try:
        payload = {"action": "get_clients"}
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)
        rows = res.get("clients", []) if isinstance(res, dict) else []

        if not rows:
            return []

        all_clients = [r.get("name", "") for r in rows if r.get("name")]
        fuzzy = set(get_close_matches(name, all_clients, n=5, cutoff=0.6))
        substring = [r for r in rows if name.lower() in (r.get("name", "").lower())]

        # Combine
        matches = []
        for r in rows:
            cname = r.get("name")
            if cname in fuzzy or r in substring:
                matches.append((
                    r.get("client_id", ""),
                    cname,
                    r.get("phone", ""),
                    f"{r.get('dob_day','')}-{r.get('dob_month','')}"
                ))

        return matches

    except Exception as e:
        log.error(f"❌ Failed to match client: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# Disambiguation Helper
# ─────────────────────────────────────────────────────────────
def _confirm_or_disambiguate(matches, action: str, wa: str, extra: str = ""):
    """If one match, return it. If many, ask Nadine to choose."""
    if not matches:
        safe_execute(
            send_whatsapp_text,
            wa,
            f"⚠ No client found. Could not {action}.",
            label=f"{action}_not_found",
        )
        return None

    if len(matches) == 1:
        return matches[0]

    # Multiple matches → prompt Nadine
    msg = "⚠ Multiple matches found. Please refine:\n\n"
    for idx, (cid, cname, cwa, dob) in enumerate(matches, start=1):
        dob_fmt = _format_dob(dob)
        msg += f"{idx}. {cname} ({cwa})"
        if dob_fmt:
            msg += f" DOB {dob_fmt}"
        msg += "\n"
    msg += f"\nReply with: {action} <full name> {extra}".strip()

    safe_execute(send_whatsapp_text, wa, msg, label=f"{action}_disambiguation")
    return None
