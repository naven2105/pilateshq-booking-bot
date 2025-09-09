#app/crud.py

from __future__ import annotations

from hashlib import sha256
from typing import Optional

from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa

# --- Lead state (expecting name) ---------------------------------------------
def lead_set_expectation(wa: str, expecting: str = "name") -> None:
    with get_session() as s:
        s.execute(
            text("""
                INSERT INTO lead_states (wa_number, expecting)
                VALUES (:wa, :ex)
                ON CONFLICT (wa_number) DO UPDATE
                  SET expecting = EXCLUDED.expecting,
                      last_prompt_at = now()
            """),
            {"wa": wa, "ex": expecting},
        )
        s.commit()

def lead_pop_expectation(wa: str) -> str | None:
    """
    Return the current expectation and clear it, or None.
    """
    with get_session() as s:
        row = s.execute(
            text("SELECT expecting FROM lead_states WHERE wa_number = :wa"),
            {"wa": wa},
        ).mappings().first()
        if not row:
            return None
        s.execute(text("DELETE FROM lead_states WHERE wa_number = :wa"), {"wa": wa})
        s.commit()
        return row["expecting"]

def lead_peek_expectation(wa: str) -> str | None:
    with get_session() as s:
        row = s.execute(
            text("SELECT expecting FROM lead_states WHERE wa_number = :wa"),
            {"wa": wa},
        ).mappings().first()
        return row["expecting"] if row else None


# ──────────────────────────────────────────────────────────────────────────────
# Clients / Bookings basics already used elsewhere
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"), {"wa": wa}).first()
        return bool(row)

def upsert_public_client(wa_number: str, name: Optional[str]) -> dict:
    """
    Create/update a lightweight client record for a public lead (plan stays NULL).
    If you enforce NOT NULL plan in schema, this will try to set 'lead'.
    """
    wa_norm = normalize_wa(wa_number)
    with get_session() as s:
        # Try to insert into clients. If your schema requires plan NOT NULL, set 'lead'.
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (COALESCE(NULLIF(:name,''), NULL), :wa, 0, COALESCE((SELECT 'lead'::text), NULL))
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
                RETURNING id, name, wa_number
            """),
            {"name": (name or "").strip(), "wa": wa_norm},
        ).mappings().first()
        return dict(row) if row else {"id": None, "name": name, "wa_number": wa_norm}

def list_clients(limit: int = 10, offset: int = 0) -> list[dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT id, COALESCE(name,'') AS name, COALESCE(wa_number,'') AS wa_number,
                       COALESCE(plan,'') AS plan, COALESCE(credits,0) AS credits
                FROM clients
                ORDER BY COALESCE(name,''), id
                LIMIT :lim OFFSET :off
            """),
            {"lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]

# ──────────────────────────────────────────────────────────────────────────────
# Admin Inbox
# ──────────────────────────────────────────────────────────────────────────────

def _digest_for(kind: str, title: str, body: str, bucket: str | None) -> str:
    raw = f"{kind}|{title}|{body}|{bucket or ''}"
    return sha256(raw.encode("utf-8")).hexdigest()

def inbox_ensure_columns():
    """
    Best-effort add columns if the table predates these fields.
    Safe to run often.
    """
    with get_session() as s:
        s.execute(text("ALTER TABLE admin_inbox ADD COLUMN IF NOT EXISTS is_unread BOOLEAN NOT NULL DEFAULT TRUE"))
        s.execute(text("ALTER TABLE admin_inbox ADD COLUMN IF NOT EXISTS action_required BOOLEAN NOT NULL DEFAULT FALSE"))

def inbox_upsert(
    kind: str,
    title: str,
    body: str,
    session_id: int | None = None,
    client_id: int | None = None,
    source: str = "system",
    status: str = "open",
    bucket: str | None = None,
    action_required: bool = False,
    digest: str | None = None,
) -> int | None:
    inbox_ensure_columns()
    if not digest:
        digest = _digest_for(kind, title, body, bucket)
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO admin_inbox
                  (kind, title, body, session_id, client_id, source, status, is_unread, action_required, bucket, digest)
                VALUES
                  (:k,   :t,    :b,   :sid,       :cid,       :src,   :st,    TRUE,      :ar,             :bk,    :dg)
                ON CONFLICT (digest) DO NOTHING
                RETURNING id
            """),
            {"k": kind, "t": title, "b": body, "sid": session_id, "cid": client_id,
             "src": source, "st": status, "ar": bool(action_required), "bk": bucket, "dg": digest}
        ).mappings().first()
        return row["id"] if row else None

def inbox_list(
    status: str | None = None,
    unread_only: bool | None = None,
    action_required: bool | None = None,
    limit: int = 20,
    offset: int = 0,
):
    with get_session() as s:
        clauses = []
        params = {"lim": int(limit), "off": int(offset)}
        if status:
            clauses.append("status = :st")
            params["st"] = status
        if unread_only is True:
            clauses.append("is_unread = TRUE")
        if action_required is True:
            clauses.append("action_required = TRUE")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = s.execute(
            text(f"""
                SELECT id, kind, title, body, session_id, client_id, source, status,
                       is_unread, action_required, bucket, created_at
                FROM admin_inbox
                {where}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params
        ).mappings().all()
        return [dict(r) for r in rows]

def inbox_get(inbox_id: int) -> Optional[dict]:
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, kind, title, body, session_id, client_id, source, status,
                   is_unread, action_required, bucket, created_at
            FROM admin_inbox WHERE id=:id
        """), {"id": inbox_id}).mappings().first()
        return dict(r) if r else None

def inbox_counts():
    with get_session() as s:
        row = s.execute(text("""
            SELECT
              COUNT(*) FILTER (WHERE status='open')           AS open_cnt,
              COUNT(*) FILTER (WHERE is_unread)               AS unread_cnt,
              COUNT(*) FILTER (WHERE action_required)         AS action_cnt,
              COUNT(*)                                        AS total_cnt
            FROM admin_inbox
        """)).mappings().first()
        return dict(row)

def inbox_mark_read(inbox_id: int):
    with get_session() as s:
        s.execute(text("UPDATE admin_inbox SET is_unread=FALSE WHERE id=:id"), {"id": inbox_id})

def inbox_mark_unread(inbox_id: int):
    with get_session() as s:
        s.execute(text("UPDATE admin_inbox SET is_unread=TRUE WHERE id=:id"), {"id": inbox_id})

def inbox_resolve(inbox_id: int, close_status: str = "closed"):
    with get_session() as s:
        s.execute(text("UPDATE admin_inbox SET status=:st, is_unread=FALSE WHERE id=:id"),
                  {"id": inbox_id, "st": close_status})

def inbox_set_action(inbox_id: int, needs_action: bool):
    with get_session() as s:
        s.execute(text("UPDATE admin_inbox SET action_required=:ar WHERE id=:id"),
                  {"id": inbox_id, "ar": bool(needs_action)})

# ──────────────────────────────────────────────────────────────────────────────
# Leads (lightweight). If table `leads` exists, we store there; otherwise we
# still log to admin_inbox and admin can “accept” to make a real client.
# ──────────────────────────────────────────────────────────────────────────────

def lead_insert(wa_number: str, name: Optional[str], note: Optional[str]) -> None:
    """
    Try to insert into leads(wa_number, name, note). If table doesn't exist,
    ignore gracefully (the inbox item still tracks the lead).
    """
    wa = normalize_wa(wa_number)
    try:
        with get_session() as s:
            s.execute(
                text("""
                    INSERT INTO leads (wa_number, name, note, created_at)
                    VALUES (:wa, NULLIF(:name,''), :note, now())
                    ON CONFLICT (wa_number) DO UPDATE
                      SET name = COALESCE(NULLIF(EXCLUDED.name,''), leads.name),
                          note = COALESCE(EXCLUDED.note, leads.note)
                """),
                {"wa": wa, "name": (name or "").strip(), "note": (note or "")[:500]}
            )
    except Exception:
        # If the table doesn't exist or fails, we don't block
        pass

def create_client_from_wa(wa_number: str, name: str) -> int | None:
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (:name, :wa, 0, COALESCE((SELECT 'lead'::text), NULL))
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name,''), clients.name)
                RETURNING id
            """),
            {"name": name.strip(), "wa": wa}
        ).mappings().first()
        return row["id"] if row else None

def lead_accept_from_inbox(inbox_id: int, name: str) -> tuple[bool, str]:
    r = inbox_get(inbox_id)
    if not r:
        return False, f"Item #{inbox_id} not found."
    if r["kind"] not in {"booking_request", "query"}:
        return False, f"Item #{inbox_id} is not a lead-type item."

    # Try to extract WA from body “From 27…”
    import re
    m = re.search(r"From\s+(\+?\d{6,15})", r["body"])
    wa = m.group(1) if m else None
    if not wa:
        return False, "Could not find a phone number in this item. Please create client manually."

    cid = create_client_from_wa(wa, name=name)
    if not cid:
        return False, "Failed to create/update client."
    inbox_resolve(inbox_id, close_status="closed")
    return True, f"Lead accepted. Client created/updated for {wa} as “{name}”."

def lead_decline_from_inbox(inbox_id: int) -> tuple[bool, str]:
    r = inbox_get(inbox_id)
    if not r:
        return False, f"Item #{inbox_id} not found."
    inbox_resolve(inbox_id, close_status="closed")
    return True, f"Lead item #{inbox_id} declined/closed."
