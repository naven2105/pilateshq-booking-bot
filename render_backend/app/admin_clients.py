"""
admin_clients.py – Phase 22e
────────────────────────────────────────────
Adds Quick Update Reply Mode for Nadine.
Features:
 • Remembers last referenced client.
 • Recognises short replies:
     - "DOB 21-May"
     - "Email tom@..."
     - "Notes prefers mornings"
 • Prompts Nadine after each add/find
   with suggestion to update details.
────────────────────────────────────────────
"""

import re
import logging
from .utils import send_whatsapp_text, safe_execute, post_to_webhook
from .config import WEBHOOK_BASE

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# In-memory tracker for last referenced client
# ─────────────────────────────────────────────
_last_client_by_admin = {}   # { wa_number: "Client Name" }

# ─────────────────────────────────────────────
# Helper: GAS call wrapper
# ─────────────────────────────────────────────
def _call_gas(action: str, payload: dict):
    try:
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets",
                              {**payload, "action": action})
        return res or {"ok": False, "error": "No response"}
    except Exception as e:
        log.error(f"[GAS ERROR] {action} :: {e}")
        return {"ok": False, "error": str(e)}

# ─────────────────────────────────────────────
# Helper: Format client summary
# ─────────────────────────────────────────────
def _format_summary(client: dict) -> str:
    if not client:
        return "⚠ Client details unavailable."
    name = client.get("name", "Unknown")
    phone = client.get("phone", "–")
    dob = f"{client.get('dob_day','')} {client.get('dob_month','')}".strip() or "Not recorded"
    email = client.get("email_address", "–") or "–"
    notes = client.get("notes", "–") or "–"
    status = client.get("status", "Active").title()
    return (
        f"👤 *{name}* ({phone})\n"
        f"🎂 DOB: {dob}\n"
        f"📧 Email: {email}\n"
        f"🗒 Notes: {notes}\n"
        f"🟢 Status: {status}"
    )

# ─────────────────────────────────────────────
# Helper: Store memory + send update prompt
# ─────────────────────────────────────────────
def _remember_and_prompt(wa: str, name: str, summary: str):
    _last_client_by_admin[wa] = name
    prompt = (
        summary
        + "\n\n💬 Would you like to add DOB, notes, or email?"
        + "\n→ e.g. 'DOB 21-May' or 'Email mary@…'"
    )
    safe_execute(send_whatsapp_text, wa, prompt)

# ─────────────────────────────────────────────
# Main handler (includes Quick-Update Mode)
# ─────────────────────────────────────────────
def handle_client_command(parsed: dict, wa: str):
    intent = parsed.get("intent")
    name = (parsed.get("name") or "").strip()
    log.info(f"[ADMIN CLIENT] intent={intent}, name={name}")

    # ── 0️⃣ Check for short replies first ──
    short = _detect_quick_update(parsed.get("raw") or "", wa)
    if short:
        _handle_quick_update(short, wa)
        return

    # 1️⃣ Add Client
    if intent == "add_client":
        number = (parsed.get("number") or "").strip()
        if not name or not number:
            safe_execute(send_whatsapp_text, wa,
                         "⚠ Use: 'Add Mary Smith 0821234567'")
            return
        res = _call_gas("add_client", {"name": name, "wa_number": number})
        if res.get("ok"):
            c = _call_gas("find_client", {"name": name}).get("client", {})
            summary = f"✅ *{name}* ({number}) added successfully.\n" + _format_summary(c)
            _remember_and_prompt(wa, name, summary)
        else:
            safe_execute(send_whatsapp_text, wa,
                         f"⚠ Could not add {name}: {res.get('error','unknown error')}")
        return

    # 2️⃣ Update DOB
    if intent == "update_dob":
        dob = parsed.get("dob", "")
        res = _call_gas("update_dob", {"name": name, "dob": dob})
        if res.get("ok"):
            c = _call_gas("find_client", {"name": name}).get("client", {})
            msg = f"✅ DOB updated for *{name}* → {dob}\n" + _format_summary(c)
        elif "invalid" in res.get("error", "").lower():
            msg = "⚠ Invalid DOB format — use 21-May or 5-Aug."
        elif "not found" in res.get("error", "").lower():
            msg = f"⚠ I couldn’t find {name} in your client list."
        else:
            msg = f"⚠ Could not update DOB for {name}."
        safe_execute(send_whatsapp_text, wa, msg)
        _last_client_by_admin[wa] = name
        return

    # 3️⃣ Update Notes
    if intent == "update_notes":
        notes = parsed.get("notes", "")
        res = _call_gas("update_notes", {"name": name, "notes": notes})
        if res.get("ok"):
            c = _call_gas("find_client", {"name": name}).get("client", {})
            msg = f"✅ Notes updated for *{name}*.\n" + _format_summary(c)
        elif "not found" in res.get("error", "").lower():
            msg = f"⚠ I couldn’t find {name} in your client list."
        else:
            msg = f"⚠ Could not update notes for {name}."
        safe_execute(send_whatsapp_text, wa, msg)
        _last_client_by_admin[wa] = name
        return

    # 4️⃣ Update Email
    if intent == "update_email":
        email = parsed.get("email", "")
        res = _call_gas("update_email", {"name": name, "email": email})
        if res.get("ok"):
            c = _call_gas("find_client", {"name": name}).get("client", {})
            msg = f"✅ Email updated for *{name}*.\n" + _format_summary(c)
        elif "not found" in res.get("error", "").lower():
            msg = f"⚠ I couldn’t find {name} in your client list."
        else:
            msg = f"⚠ Could not update email for {name}."
        safe_execute(send_whatsapp_text, wa, msg)
        _last_client_by_admin[wa] = name
        return

    # 5️⃣ Find Client
    if intent == "find_client":
        res = _call_gas("find_client", {"name": name})
        if res.get("ok") and res.get("client"):
            summary = _format_summary(res["client"])
            _remember_and_prompt(wa, name, summary)
        else:
            safe_execute(send_whatsapp_text, wa,
                         f"⚠ I couldn’t find {name} in your client list.")
        return

    # 6️⃣ Fallback
    safe_execute(
        send_whatsapp_text,
        wa,
        "⚠ I didn’t recognise that command. Try 'Find Mary Smith' or 'DOB 21-May'.",
    )

# ─────────────────────────────────────────────
# Quick Update Mode helpers
# ─────────────────────────────────────────────
def _detect_quick_update(text: str, wa: str) -> dict | None:
    """Detects 'DOB …', 'Email …', or 'Notes …' short replies."""
    t = text.strip()
    name = _last_client_by_admin.get(wa)
    if not name:
        return None
    # DOB pattern
    if m := re.match(r"(?i)^dob\s+(\d{1,2}[-/ ]?[A-Za-z]{3,9})$", t):
        return {"intent": "update_dob", "name": name, "dob": m.group(1)}
    # Email pattern
    if m := re.match(r"(?i)^email\s+([^\s@]+@[^\s@]+\.[^\s@]+)$", t):
        return {"intent": "update_email", "name": name, "email": m.group(1)}
    # Notes pattern
    if m := re.match(r"(?i)^notes?\s+(.+)$", t):
        return {"intent": "update_notes", "name": name, "notes": m.group(1)}
    return None


def _handle_quick_update(parsed: dict, wa: str):
    """Executes the quick update immediately."""
    intent = parsed["intent"]
    log.info(f"[QUICK UPDATE] {intent} for {parsed['name']}")
    handle_client_command(parsed, wa)
