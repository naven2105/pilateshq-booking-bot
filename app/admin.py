# app/admin.py
from __future__ import annotations

import re
import logging
from typing import Optional

from .utils import send_whatsapp_text, normalize_wa
from . import crud

INBOX_HELP = (
    "📥 *Admin Inbox commands*\n"
    "• INBOX — show latest admin items\n"
    "• VIEW <id> — view a single inbox item\n"
    "• CLOSE <id> — mark an inbox item closed"
)


def _fmt_inbox_summary() -> str:
    """Compact summary: counts by kind + last few entries per kind."""
    counts = {}
    try:
        counts = crud.inbox_counts_by_kind()
    except Exception:
        logging.exception("inbox_counts_by_kind failed")

    # Always include the four primary kinds for a consistent header
    kinds = ["proposal", "query", "hourly", "daily"]
    hdr = "📥 *Admin Inbox*  |  " + "  ".join(
        f"{k.capitalize()}({int(counts.get(k, 0))})" for k in kinds
    )

    lines = [hdr, ""]
    try:
        recent = crud.inbox_recent(limit_per_kind=5)
        for k in kinds:
            items = (recent or {}).get(k, [])
            if not items:
                continue
            lines.append(f"— *{k.upper()}* —")
            for it in items:
                # Example line: #123 • Hourly update  [open]
                title = it.get("title") or "(no title)"
                status = it.get("status") or "open"
                lines.append(f"#{it['id']} • {title}  [{status}]")
            lines.append("")  # spacer
    except Exception:
        logging.exception("inbox_recent failed")
        lines.append("_(Recent items unavailable right now.)_")
        lines.append("")

    lines.append(INBOX_HELP)
    return "\n".join(lines)


def _fmt_inbox_item(id_: int) -> str:
    """Full single item view with metadata and body."""
    try:
        it = crud.inbox_get(id_)
    except Exception:
        logging.exception("inbox_get failed")
        it = None

    if not it:
        return f"Item #{id_} not found."

    lines = [
        f"#{it['id']} • *{it['kind'].upper()}*  [{it['status']}]",
        f"*Title:* {it.get('title') or '(no title)'}",
        f"*Source:* {it.get('source') or 'system'}    *Bucket:* {it.get('bucket') or '-'}",
        f"*Created:* {it.get('created_at')}",
        "",
        it.get("body") or "(no body)",
        "",
        f"Actions: CLOSE {id_}"
    ]
    return "\n".join(lines)


def _handle_text_command(to_wa: str, text: str) -> None:
    """
    Parse and execute INBOX / VIEW / CLOSE.
    """
    t = (text or "").strip()

    # INBOX (exact match, case-insensitive) or HELP
    if re.fullmatch(r"(inbox|help)", t, flags=re.IGNORECASE):
        send_whatsapp_text(to_wa, _fmt_inbox_summary())
        return

    # VIEW <id>
    m = re.match(r"^view\s+(\d+)$", t, flags=re.IGNORECASE)
    if m:
        send_whatsapp_text(to_wa, _fmt_inbox_item(int(m.group(1))))
        return

    # CLOSE <id>
    m = re.match(r"^close\s+(\d+)$", t, flags=re.IGNORECASE)
    if m:
        try:
            crud.inbox_mark_closed(int(m.group(1)))
            send_whatsapp_text(to_wa, f"Item #{m.group(1)} marked closed.")
        except Exception:
            logging.exception("inbox_mark_closed failed")
            send_whatsapp_text(to_wa, "Sorry — couldn’t close that item right now.")
        return

    # Fallback help
    send_whatsapp_text(to_wa, f"Unknown admin command.\n\n{INBOX_HELP}")


def handle_admin_action(sender_wa: str, reply_id: Optional[str] = None, text: Optional[str] = None) -> None:
    """
    Entry point used by router.py.

    Your router sometimes invokes:
      handle_admin_action(wa, msg_id)
    and as a fallback:
      handle_admin_action(wa, msg_id, body)

    We normalize the sender number and:
      • If text is present → parse commands.
      • If no text → show the INBOX summary to keep things useful.
    """
    to = normalize_wa(sender_wa)

    # When an interactive button/list reply arrives, router may pass the chosen title as `text`.
    if text and text.strip():
        _handle_text_command(to, text.strip())
        return

    # No text available — default to showing the inbox summary (nice UX).
    send_whatsapp_text(to, _fmt_inbox_summary())
