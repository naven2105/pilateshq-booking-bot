# app/admin.py

from __future__ import annotations
import logging
from sqlalchemy import text

from .utils import send_whatsapp_text
from .db import get_session
from .config import TZ_NAME
# import the same helpers your cron uses
from .tasks import _fmt_today_block, _rows_next_hour

def _admin_hourly_text() -> str:
    """
    Build the same hourly message as /tasks/admin-notify (upcoming + next hour).
    We don’t bother with the 04:00 full-day branch when sent manually.
    """
    body_today = _fmt_today_block(upcoming_only=True, include_names=True)
    nxt = _rows_next_hour()
    if nxt:
        lines = []
        for r in nxt:
            names = (r.get("names") or "").strip()
            nm = names if names else "(no bookings)"
            status = (r.get("status") or "").lower()
            is_full = (status == "full") or (r.get("booked_count", 0) >= r.get("capacity", 0))
            badge = "🔒 full" if is_full else "✅ open"
            lines.append(f"• {str(r['start_time'])[:5]} – {nm}  ({badge})")
        nxt_block = "🕒 Next hour:\n" + "\n".join(lines)
    else:
        nxt_block = "🕒 Next hour: no upcoming session"

    return f"{body_today}\n\n{nxt_block}"

def _is_after_20_sast() -> bool:
    """
    Return True if current SA-local time is >= 20:00 (no more hourlies after recap).
    """
    with get_session() as s:
        # Evaluate in DB to stay in sync with SQL usage elsewhere
        row = s.execute(text(f"SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz)::time AS t"),
                        {"tz": TZ_NAME}).mappings().first()
        t = str(row["t"])[:5]  # 'HH:MM'
        return t >= "20:00"

def handle_admin_action(wa: str, reply_id: str | None = None, body: str | None = None) -> None:
    """
    Minimal command router for admins.
    Accepts plain text commands like 'hourly', 'recap', 'help'.
    """
    txt = (body or "").strip().lower()

    # QUICK HELP
    if txt in {"help", "menu"}:
        send_whatsapp_text(wa,
            "🔧 Admin commands:\n"
            "• hourly – show today’s upcoming + next-hour\n"
            "• recap – show full-day recap (like 20:00)\n"
        )
        return

    # HOURLY: block hourlies after 20:00 SAST (your rule)
    if txt == "hourly":
        if _is_after_20_sast():
            send_whatsapp_text(wa, "It’s after 20:00 SAST—no further hourly updates today ✅")
            return
        try:
            send_whatsapp_text(wa, _admin_hourly_text())
        except Exception:
            logging.exception("admin hourly build failed")
            send_whatsapp_text(wa, "Sorry—failed to build hourly update.")
        return

    # RECAP: a manual “20:00-style” full-day view
    if txt == "recap":
        try:
            msg = _fmt_today_block(upcoming_only=False, include_names=True)
            send_whatsapp_text(wa, msg)
        except Exception:
            logging.exception("admin recap build failed")
            send_whatsapp_text(wa, "Sorry—failed to build daily recap.")
        return

    # FALLBACK
    send_whatsapp_text(wa, "Unknown admin message. Type *help* for commands.")
