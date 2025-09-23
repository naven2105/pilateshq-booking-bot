"""
Handles inbound admin actions (Nadine / super-admin).
Now integrated with admin_nudge.py so that:
 - Sick / No-show / Cancel actions also trigger a nudge log
 - Wrapped in safe_execute() for reliability
"""

from __future__ import annotations
import logging
from typing import Optional
from sqlalchemy import text
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from .admin_nlp import parse_admin_command, parse_admin_client_command
from .booking import admin_reserve, create_recurring_bookings, create_multi_recurring_bookings
from .db import get_session
from . import admin_nudge  # for nudges

log = logging.getLogger(__name__)


def _find_or_create_client(name: str, wa_number: str | None = None) -> tuple[int, str] | tuple[None, None]:
    """Look up a client by name. If not found and wa_number is given, create."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, wa_number FROM clients WHERE lower(name)=lower(:n)"),
            {"n": name},
        ).first()
        if row:
            return row[0], row[1]
        if wa_number:
            r = s.execute(
                text("INSERT INTO clients (name, wa_number, phone, package_type) "
                     "VALUES (:n, :wa, :wa, 'manual') RETURNING id, wa_number"),
                {"n": name, "wa": wa_number},
            )
            cid, wnum = r.first()
            return cid, wnum
    return None, None


def _mark_lead_converted(wa_number: str, client_id: int):
    """Mark a lead as converted once promoted to client."""
    with get_session() as s:
        s.execute(
            text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
            {"wa": wa_number},
        )
    log.info(f"Lead {wa_number} promoted → client {client_id}")


def _find_session(date: str, time: str) -> int | None:
    """Find a session by date+time. Returns session_id or None."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT id FROM sessions
                WHERE session_date = :d AND start_time = :t
            """),
            {"d": date, "t": time},
        ).first()
        return row[0] if row else None


def _cancel_next_booking(client_id: int) -> bool:
    """Cancel the next future booking for a client."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT id FROM bookings
                WHERE client_id = :cid AND status = 'active'
                  AND session_id IN (
                      SELECT id FROM sessions WHERE session_date >= CURRENT_DATE
                  )
                ORDER BY session_id ASC
                LIMIT 1
            """),
            {"cid": client_id},
        ).first()
        if not row:
            return False
        bid = row[0]
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:bid"), {"bid": bid})
        return True


def _mark_today_booking(client_id: int, new_status: str) -> bool:
    """Mark today’s booking for client as sick/no_show."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT b.id FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                WHERE b.client_id=:cid AND b.status='active'
                  AND s.session_date = CURRENT_DATE
                LIMIT 1
            """),
            {"cid": client_id},
        ).first()
        if not row:
            return False
        bid = row[0]
        s.execute(text("UPDATE bookings SET status=:st WHERE id=:bid"), {"st": new_status, "bid": bid})
        return True


def _log_notification(client_id: int, message: str):
    """Insert a record into notifications_log audit table."""
    with get_session() as s:
        s.execute(
            text("INSERT INTO notifications_log (client_id, message, created_at) VALUES (:cid, :msg, now())"),
            {"cid": client_id, "msg": message},
        )


def _notify_client(wa_number: str, message: str):
    """Send WhatsApp text to a client and log it."""
    if not wa_number:
        return
    safe_execute(send_whatsapp_text, normalize_wa(wa_number), message, label="notify_client")
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number=:wa"),
            {"wa": normalize_wa(wa_number)},
        ).first()
        if row:
            _log_notification(row[0], message)


def handle_admin_action(from_wa: str, msg_id: Optional[str], body: str, btn_id: Optional[str] = None):
    """Handle inbound admin actions from WhatsApp."""
    log.info(f"[ADMIN] from={from_wa} body={body!r} btn_id={btn_id!r}")

    wa = normalize_wa(from_wa)
    text_in = (body or "").strip()

    # ─────────────── Menu ───────────────
    if text_in.lower() in {"hi", "menu", "help"}:
        safe_execute(send_whatsapp_text, wa,
            "🛠 Admin Menu\n\n"
            "• Book Sessions → e.g. 'Book Mary on 2025-09-21 08:00 single'\n"
            "• Recurring Sessions → e.g. 'Book Mary every Tuesday 09h00 duo'\n"
            "• Manage Clients → e.g. 'Add client Alice with number 082...'\n"
            "• Attendance Updates → e.g. 'Peter is off sick.'\n"
            "Type your command directly.",
            label="admin_menu"
        )
        return

    # ─────────────── Bookings ───────────────
    parsed = parse_admin_command(text_in, wa_number=wa)
    if parsed:
        intent = parsed["intent"]
        log.info(f"[ADMIN BOOKING] parsed={parsed}")

        if intent == "book_single":
            client_id, wnum = _find_or_create_client(parsed["name"], parsed.get("wa_number"))
            if client_id:
                _mark_lead_converted(wnum, client_id)
            sid = _find_session(parsed["date"], parsed["time"])
            if not sid:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ No session found on {parsed['date']} at {parsed['time']}.",
                    label="book_single_fail"
                )
                return
            ok = admin_reserve(client_id, sid, 1)
            if ok:
                safe_execute(send_whatsapp_text, wa,
                    f"✅ Session booked for {parsed['name']} on {parsed['date']} at {parsed['time']}.",
                    label="book_single_ok"
                )
            else:
                safe_execute(send_whatsapp_text, wa,
                    f"❌ Could not reserve — session is full.",
                    label="book_single_full"
                )
            return

        if intent == "book_recurring":
            client_id, wnum = _find_or_create_client(parsed["name"], parsed.get("wa_number"))
            if client_id:
                _mark_lead_converted(wnum, client_id)
            created = create_recurring_bookings(client_id, parsed["weekday"], parsed["time"], parsed["slot_type"])
            safe_execute(send_whatsapp_text, wa,
                f"📅 Created {created} weekly bookings for {parsed['name']} ({parsed['slot_type']}).",
                label="book_recurring"
            )
            return

        if intent == "book_recurring_multi":
            client_id, wnum = _find_or_create_client(parsed["name"], parsed.get("wa_number"))
            if client_id:
                _mark_lead_converted(wnum, client_id)
            created = create_multi_recurring_bookings(client_id, parsed["slots"])
            safe_execute(send_whatsapp_text, wa,
                f"📅 Created {created} recurring bookings for {parsed['name']} across multiple days.",
                label="book_multi"
            )
            return

    # ─────────────── Clients / Attendance ───────────────
    parsed = parse_admin_client_command(text_in)
    if parsed:
        intent = parsed["intent"]
        log.info(f"[ADMIN CLIENT] parsed={parsed}")

        if intent == "add_client":
            name = parsed["name"]
            number = parsed["number"].replace("+", "")
            if number.startswith("0"):
                number = "27" + number[1:]
            cid, wnum = _find_or_create_client(name, number)
            if cid:
                _mark_lead_converted(wnum, cid)
                safe_execute(send_whatsapp_text, wa,
                    f"✅ Client '{name}' added with number {wnum}. (id={cid})",
                    label="add_client_ok"
                )
            else:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ Could not add client '{name}'.",
                    label="add_client_fail"
                )
            return

        if intent == "cancel_next":
            cid, wnum = _find_or_create_client(parsed["name"])
            if not cid:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ No client found named '{parsed['name']}'.",
                    label="cancel_next_fail"
                )
                return
            ok = _cancel_next_booking(cid)
            if ok:
                _notify_client(wnum, "Hi! Your next session has been cancelled by the studio. Please contact us to reschedule 💜")
                safe_execute(send_whatsapp_text, wa,
                    f"✅ Next session for {parsed['name']} cancelled and client notified.",
                    label="cancel_next_ok"
                )
                admin_nudge.notify_cancel(parsed["name"], wnum, "next session")
            else:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ No active future booking found for {parsed['name']}.",
                    label="cancel_next_none"
                )
            return

        if intent == "off_sick_today":
            cid, wnum = _find_or_create_client(parsed["name"])
            if not cid:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ No client found named '{parsed['name']}'.",
                    label="sick_fail"
                )
                return
            ok = _mark_today_booking(cid, "sick")
            if ok:
                _notify_client(wnum, "Hi! We’ve marked you as sick for today’s session. Wishing you a speedy recovery 🌸")
                safe_execute(send_whatsapp_text, wa,
                    f"🤒 Marked {parsed['name']} as sick today and client notified.",
                    label="sick_ok"
                )
                admin_nudge.notify_sick(parsed["name"], wnum, "today")
            else:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ No active booking today for {parsed['name']}.",
                    label="sick_none"
                )
            return

        if intent == "no_show_today":
            cid, wnum = _find_or_create_client(parsed["name"])
            if not cid:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ No client found named '{parsed['name']}'.",
                    label="noshow_fail"
                )
                return
            ok = _mark_today_booking(cid, "no_show")
            if ok:
                _notify_client(wnum, "Hi! You missed today’s session. Please reach out if you’d like to rebook.")
                safe_execute(send_whatsapp_text, wa,
                    f"🚫 Marked {parsed['name']} as no-show and client notified.",
                    label="noshow_ok"
                )
                admin_nudge.notify_no_show(parsed["name"], wnum, "today")
            else:
                safe_execute(send_whatsapp_text, wa,
                    f"⚠ No active booking today for {parsed['name']}.",
                    label="noshow_none"
                )
            return

    # ─────────────── Fallback ───────────────
    safe_execute(send_whatsapp_text, wa,
        "⚠ Unknown admin command. Reply 'menu' for options.",
        label="admin_fallback"
    )
