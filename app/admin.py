# app/admin.py
from __future__ import annotations

import logging
from typing import Optional, Dict, Literal, List, Tuple

from .utils import send_whatsapp_text
from .crud import (
    find_clients_by_prefix,
    find_one_client,
    client_upcoming_bookings,
    client_recent_history,
)

# ──────────────────────────────────────────────────────────────────────────────
# Ephemeral admin context
# ──────────────────────────────────────────────────────────────────────────────

AdminMode = Literal["idle", "client_search"]

_ADMIN_CTX: Dict[str, AdminMode] = {}   # key = admin wa, value = mode


def _set_mode(wa: str, mode: AdminMode) -> None:
    _ADMIN_CTX[wa] = mode


def _get_mode(wa: str) -> AdminMode:
    return _ADMIN_CTX.get(wa, "idle")


# ──────────────────────────────────────────────────────────────────────────────
# Admin Menu Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _admin_menu_text() -> str:
    return (
        "🛠 *Admin Menu*\n"
        "• Inbox – type *inbox*\n"
        "• Clients – type *clients* (search & view)\n"
        "• Sessions – type *sessions*\n"
        "• Hourly – type *hourly*\n"
        "• Recap – type *recap*\n"
        "• Menu – type *menu*\n"
    )


def _clients_help_text() -> str:
    return (
        "👤 *Client Search*\n"
        "• Type *≥3 letters* of the client’s *name* (e.g., `nad`, `tha`).\n"
        "• Or type WA number prefix (e.g., `2777`).\n"
        "• To open a profile: `view <name>`, `view <wa>`, or `view #<id>`\n"
        "• Type *menu* to go back."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _parse_view_command(text: str) -> Optional[str]:
    """
    Accepts:
      - 'view something'
      - 'v something'
    Returns the string after the command, trimmed, or None.
    """
    t = (text or "").strip()
    low = t.lower()
    if low.startswith("view "):
        return t[5:].strip()
    if low.startswith("v "):
        return t[2:].strip()
    if low == "view" or low == "v":
        return ""  # user typed view without arg
    return None


def _format_client_hits(rows: List[dict]) -> str:
    if not rows:
        return "No matches found. Try different letters (min 3)."

    lines = ["🔎 *Matches*"]
    for r in rows:
        name = (r.get("name") or "").strip() or "—"
        wa = r.get("wa_number") or "—"
        plan = (r.get("plan") or "—").strip() or "—"
        credits = r.get("credits")
        cid = r.get("id")
        lines.append(f"• #{cid}  {name}  ({wa})  – plan: {plan}, credits: {credits}")
    lines.append("\nTip: `view #<id>` to open a profile.")
    return "\n".join(lines)


def _fmt_bookings(rows: List[dict], title: str) -> str:
    if not rows:
        return f"{title}\n— none —"
    out = [title]
    for r in rows:
        dt = r.get("local_dt", "")  # 'YYYY-MM-DD HH:MM'
        status = r.get("status", "")
        out.append(f"• {dt}  ({status})")
    return "\n".join(out)


def _format_client_profile(client: dict) -> str:
    name = (client.get("name") or "").strip() or "—"
    wa = client.get("wa_number") or "—"
    plan = (client.get("plan") or "—").strip() or "—"
    credits = client.get("credits")
    cid = client.get("id")

    header = f"👤 *Client #{cid}*\n{name}  ({wa})\nPlan: {plan} | Credits: {credits}"

    # Fetch upcoming + a tiny history
    upcoming = client_upcoming_bookings(cid, limit=6)
    recent   = client_recent_history(cid, limit=3)

    body = [
        header,
        _fmt_bookings(upcoming, "🗓 *Upcoming*"),
        _fmt_bookings(recent, "📜 *Recent*"),
        "\nQuick actions (type):",
        "• `message #ID <text>` – send WhatsApp",
        "• `cancel #ID <YYYY-MM-DD HH:MM>` – request cancellation",
        "• `menu` – back to Admin Menu",
    ]
    return "\n".join(body)


# ──────────────────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────────────────

def handle_admin_action(admin_wa: str, reply_id: Optional[str] = None,
                        body: str = "", btn_id: Optional[str] = None) -> None:
    """
    Simplified admin handler:
    - 'menu' → menu
    - 'clients' → client search mode
    - In client search mode:
        • ≥3 chars → search
        • 'view <wa|name|#id>' → open profile
    """
    try:
        text = (body or "").strip()
        tlow = text.lower()

        # Button ids (if you wire WA interactive buttons later)
        if btn_id:
            if btn_id == "adm_menu":
                _set_mode(admin_wa, "idle")
                send_whatsapp_text(admin_wa, _admin_menu_text())
                return
            if btn_id == "adm_clients":
                _set_mode(admin_wa, "client_search")
                send_whatsapp_text(admin_wa, _clients_help_text())
                return

        # Global keywords
        if tlow in {"menu", "help", "hi", "hello", "admin"}:
            _set_mode(admin_wa, "idle")
            send_whatsapp_text(admin_wa, _admin_menu_text())
            return

        if tlow == "clients":
            _set_mode(admin_wa, "client_search")
            send_whatsapp_text(admin_wa, _clients_help_text())
            return

        mode = _get_mode(admin_wa)

        # ── Client search mode
        if mode == "client_search":
            # Handle 'view …'
            view_arg = _parse_view_command(text)
            if view_arg is not None:
                q = (view_arg or "").strip()
                if not q:
                    send_whatsapp_text(
                        admin_wa,
                        "Usage:\n• `view #109`\n• `view 2777…`\n• `view Nadine`\n\n" + _clients_help_text()
                    )
                    return

                # Resolve one client
                client = find_one_client(q)
                if not client:
                    send_whatsapp_text(admin_wa, "No client matched that query.\n\n" + _clients_help_text())
                    return

                send_whatsapp_text(admin_wa, _format_client_profile(client) + "\n\n" + _clients_help_text())
                return

            # Exit / back
            if tlow in {"exit", "quit", "back"}:
                _set_mode(admin_wa, "idle")
                send_whatsapp_text(admin_wa, "Exited client search.\n\n" + _admin_menu_text())
                return

            # Prefix search
            q = text.strip()
            if len(q) >= 3:
                rows = find_clients_by_prefix(q, limit=10)
                send_whatsapp_text(admin_wa, _format_client_hits(rows) + "\n\n" + _clients_help_text())
                return

            send_whatsapp_text(admin_wa, "Please type at least *3 characters*.\n\n" + _clients_help_text())
            return

        # Other admin stubs
        if tlow == "hourly":
            send_whatsapp_text(
                admin_wa,
                "Hourly summary will continue to arrive each hour automatically.\n\n" + _admin_menu_text()
            )
            return

        if tlow == "recap":
            send_whatsapp_text(
                admin_wa,
                "The 20:00 daily recap will be sent automatically.\n\n" + _admin_menu_text()
            )
            return

        if tlow == "inbox":
            send_whatsapp_text(
                admin_wa,
                "Inbox coming soon: you'll see unread/actionable items here.\n\n" + _admin_menu_text()
            )
            return

        if tlow == "sessions":
            send_whatsapp_text(
                admin_wa,
                "Sessions quick view coming soon.\n\n" + _admin_menu_text()
            )
            return

        # Fallback
        if mode == "client_search":
            send_whatsapp_text(admin_wa, _clients_help_text())
        else:
            send_whatsapp_text(admin_wa, "Unknown admin message.\n\n" + _admin_menu_text())

    except Exception:
        logging.exception("handle_admin_action failed")
