"""
schedule_router.py – Phase 16 (Client Experience)
──────────────────────────────────────────────────────────────────────────────
Features
• POST /schedule/book-weekly       → Nadine books weekly recurring sessions
• POST /schedule/run-reminders     → week_ahead | day_before | hour_before
• POST /schedule/mark-reschedule   → mark client’s NEXT session as Reschedule_Pending
• GET  /schedule/admin-digest      → when=evening (tomorrow) | morning (today)

Notes
• All data writes happen in Google Apps Script (GAS); this service orchestrates
  and handles WhatsApp messaging.
• We reuse Clients sheet to fetch WhatsApp numbers (returned by GAS).
• No client-to-client messaging: reminders go to clients; reschedule notice goes only to Nadine.
──────────────────────────────────────────────────────────────────────────────
"""
import os
import logging
import requests
from flask import Blueprint, request, jsonify
from .utils import send_safe_message

bp = Blueprint("schedule_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ──────────────────────────────────────────────────────────────
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")  # Same Script Web App URL
NADINE_WA = os.getenv("NADINE_WA", "")

# WhatsApp templates (existing, safe, generic)
TPL_ADMIN = "admin_generic_alert_us"
TPL_CLIENT_REMINDER = "client_session_reminder_us"

# ── Helpers ──────────────────────────────────────────────────────────────────
def _post_gas(payload: dict, timeout: int = 25) -> dict:
    if not GAS_INVOICE_URL:
        return {"ok": False, "error": "Missing GAS_INVOICE_URL"}
    try:
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=timeout)
        return r.json() if r.ok else {"ok": False, "error": f"GAS HTTP {r.status_code}"}
    except Exception as e:
        log.error(f"GAS call failed: {e}")
        return {"ok": False, "error": str(e)}

def _flat(text: str) -> str:
    if not text:
        return ""
    s = text.replace("\n", " ").replace("\t", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip()

# ── Routes ───────────────────────────────────────────────────────────────────
@bp.route("/book-weekly", methods=["POST"])
def book_weekly():
    """
    Body:
    {
      "client_name": "Fatima Khan",
      "weekday": "Tuesday",          # Monday..Sunday
      "time": "09:00",               # 24h
      "session_type": "Group",       # Group | Duo | Private
      "weeks": 12,                   # default 12
      "start_date": "2025-10-28"     # optional; next occurrence if omitted
    }
    """
    data = request.get_json(force=True)
    for k in ("client_name", "weekday", "time", "session_type"):
        if not data.get(k):
            return jsonify({"ok": False, "error": f"Missing {k}"}), 400

    payload = {
        "action": "schedule_add_recurring",
        "client_name": data["client_name"],
        "weekday": data["weekday"],
        "time": data["time"],
        "session_type": data["session_type"],
        "weeks": data.get("weeks", 12),
        "start_date": data.get("start_date")  # may be None
    }
    resp = _post_gas(payload)
    if not resp.get("ok"):
        send_safe_message(
            NADINE_WA, _flat(f"⚠️ Could not add weekly sessions for {data['client_name']}: {resp.get('error')}"),
            is_template=True, template_name=TPL_ADMIN, variables=[_flat(f"⚠️ Could not add weekly sessions for {data['client_name']}: {resp.get('error')}")],
            label="schedule_book_weekly_error"
        )
        return jsonify(resp), 502

    # Confirm to Nadine
    msg = _flat(f"📅 Booked {resp.get('added', 0)} session(s) for {data['client_name']} – "
                f"{data['weekday']} {data['time']} ({data['session_type']}).")
    send_safe_message(NADINE_WA, msg, is_template=True, template_name=TPL_ADMIN, variables=[msg], label="schedule_book_weekly")
    return jsonify({"ok": True, **resp})

@bp.route("/run-reminders", methods=["POST"])
def run_reminders():
    """
    Body: {"scope":"week_ahead" | "day_before" | "hour_before"}
    Sends reminders to clients; returns count.
    """
    data = request.get_json(force=True)
    scope = (data.get("scope") or "").strip().lower()
    if scope not in ("week_ahead", "day_before", "hour_before"):
        return jsonify({"ok": False, "error": "Invalid scope"}), 400

    resp = _post_gas({"action": "schedule_upcoming", "scope": scope})
    if not resp.get("ok"):
        send_safe_message(NADINE_WA,
                          _flat(f"⚠️ Reminders failed: {resp.get('error')}"),
                          is_template=True, template_name=TPL_ADMIN, variables=[_flat(f"⚠️ Reminders failed: {resp.get('error')}")],
                          label="schedule_run_reminders_error")
        return jsonify(resp), 502

    # GAS returns: { ok:true, sessions:[{client_name, when, type, wa_number}] }
    sent = 0
    for sess in resp.get("sessions", []):
        to = sess.get("wa_number")
        if not to:
            continue
        text = _flat(f"Hi {sess.get('client_name')}, reminder for your PilatesHQ {sess.get('type')} "
                     f"session at {sess.get('when')}. Reply 'reschedule' if you need to move it.")
        try:
            send_safe_message(to, text, is_template=True, template_name=TPL_CLIENT_REMINDER, variables=[text], label=f"rem_{scope}")
            sent += 1
        except Exception as e:
            log.error(f"Reminder send failed for {to}: {e}")

    # Notify Nadine (brief)
    send_safe_message(NADINE_WA, _flat(f"✅ {sent} reminder(s) sent ({scope})."),
                      is_template=True, template_name=TPL_ADMIN, variables=[_flat(f"✅ {sent} reminder(s) sent ({scope}).")],
                      label="schedule_run_reminders")
    return jsonify({"ok": True, "sent": sent})

@bp.route("/mark-reschedule", methods=["POST"])
def mark_reschedule():
    """
    Body: { "client_name": "Fatima Khan" }
    Marks NEXT upcoming session as Reschedule_Pending and alerts Nadine.
    """
    data = request.get_json(force=True)
    client = (data.get("client_name") or "").strip()
    if not client:
        return jsonify({"ok": False, "error": "Missing client_name"}), 400

    resp = _post_gas({"action": "schedule_mark_reschedule", "client_name": client})
    if not resp.get("ok"):
        send_safe_message(NADINE_WA,
                          _flat(f"⚠️ Could not mark reschedule for {client}: {resp.get('error')}"),
                          is_template=True, template_name=TPL_ADMIN, variables=[_flat(f"⚠️ Could not mark reschedule for {client}: {resp.get('error')}")],
                          label="schedule_mark_reschedule_error")
        return jsonify(resp), 502

    # Tell Nadine only
    when = resp.get("when", "the next session")
    text = _flat(f"🔄 {client} rescheduled; marked {when} as *Reschedule Pending*. Please discuss new time directly.")
    send_safe_message(NADINE_WA, text, is_template=True, template_name=TPL_ADMIN, variables=[text], label="schedule_mark_reschedule")
    return jsonify({"ok": True, **resp})

@bp.route("/admin-digest", methods=["GET"])
def admin_digest():
    """
    Query:
      when=evening → show tomorrow’s sessions (evening digest)
      when=morning → show today’s sessions   (morning digest)
    """
    when = (request.args.get("when") or "").strip().lower()
    if when not in ("evening", "morning"):
        return jsonify({"ok": False, "error": "when must be evening|morning"}), 400

    resp = _post_gas({"action": "schedule_admin_summary", "when": when})
    if not resp.get("ok"):
        send_safe_message(NADINE_WA,
                          _flat(f"⚠️ Admin digest failed: {resp.get('error')}"),
                          is_template=True, template_name=TPL_ADMIN, variables=[_flat(f"⚠️ Admin digest failed: {resp.get('error')}")],
                          label="schedule_admin_digest_error")
        return jsonify(resp), 502

    # One compact summary line to Nadine
    summary = resp.get("summary", "No sessions.")
    send_safe_message(NADINE_WA, _flat(summary), is_template=True, template_name=TPL_ADMIN, variables=[_flat(summary)], label=f"schedule_admin_digest_{when}")
    return jsonify({"ok": True, "summary": summary})

@bp.route("", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Schedule Router",
        "endpoints": [
            "/schedule/book-weekly",
            "/schedule/run-reminders",
            "/schedule/mark-reschedule",
            "/schedule/admin-digest"
        ]
    }), 200
