# app/crud.py
from __future__ import annotations

from typing import Optional, List
from hashlib import sha256
from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa



# ──────────────────────────────────────────────────────────────────────────────
# Existence + create/ensure lead client
# ──────────────────────────────────────────────────────────────────────────────

def client_exists_by_wa(wa_number: str) -> bool:
    """Return True if a client exists for this normalized WA number."""
    wa = normalize_wa(wa_number)
    if not wa:
        return False
    with get_session() as s:
        row = s.execute(text("SELECT 1 FROM clients WHERE wa_number = :wa LIMIT 1"),
                        {"wa": wa}).first()
        return bool(row)

def upsert_public_client(wa_number: str, name: Optional[str]) -> dict:
    """
    Ensure a client (lead) row exists for this number.
    - Normalizes WA number
    - Uses placeholder name like 'Guest 4607' if none given
    - Sets plan='lead', credits=0 so NOT NULL constraints are satisfied
    Returns dict(id, name, wa_number)
    """
    wa = normalize_wa(wa_number)
    if not wa:
        raise ValueError("Invalid WhatsApp number")

    safe_name = (name or "").strip()
    if not safe_name:
        tail4 = wa[-4:] if len(wa) >= 4 else wa
        safe_name = f"Guest {tail4}"

    with get_session() as s:
        row = s.execute(text("""
            INSERT INTO clients (name, wa_number, credits, plan)
            VALUES (:name, :wa, 0, 'lead')
            ON CONFLICT (wa_number)
            DO UPDATE SET
              name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
            RETURNING id, name, wa_number
        """), {"name": safe_name, "wa": wa}).mappings().first()
        return dict(row)

# ──────────────────────────────────────────────────────────────────────────────
# Admin inbox (idempotent writer)
# ──────────────────────────────────────────────────────────────────────────────

def inbox_upsert(
    *,
    kind: str,
    title: str,
    body: str,
    source: str = "system",
    status: str = "open",
    is_unread: bool = True,
    action_required: bool = False,
    bucket: str | None = None,
    session_id: int | None = None,
    client_id: int | None = None,
):
    # Accept legacy/aliases
    alias_map = {"daily": "recap"}
    kind = alias_map.get(kind, kind)

    allowed = {"booking_request", "query", "hourly", "recap", "system"}
    if kind not in allowed:
        raise ValueError(f"Unsupported inbox kind: {kind}")

    # Idempotency on (kind, title, body, bucket)
    digest = sha256(f"{kind}|{title}|{body}|{bucket or ''}".encode("utf-8")).hexdigest()

    sql = text("""
        INSERT INTO admin_inbox
          (kind, title, body, session_id, client_id, source, status,
           is_unread, action_required, bucket, digest)
        VALUES
          (:k,   :t,    :b,   :sid,       :cid,       :src,   :st,
           :ur,      :ar,             :bk,    :dg)
        ON CONFLICT (digest) DO NOTHING
        RETURNING id
    """)

    with get_session() as s:
        row = s.execute(sql, {
            "k": kind, "t": title, "b": body,
            "sid": session_id, "cid": client_id,
            "src": source, "st": status,
            "ur": bool(is_unread), "ar": bool(action_required),
            "bk": bucket, "dg": digest,
        }).mappings().first()
        return (row or {}).get("id")

# ──────────────────────────────────────────────────────────────────────────────
# Optional search helpers (used by admin search / menus)
# ──────────────────────────────────────────────────────────────────────────────

def find_clients_by_prefix(prefix: str, limit: int = 10, offset: int = 0) -> List[dict]:
    """Find clients by name prefix (case-insensitive) or WA prefix."""
    q = (prefix or "").strip()
    if not q:
        return []
    with get_session() as s:
        rows = s.execute(text("""
            SELECT
              id,
              COALESCE(name,'')      AS name,
              COALESCE(wa_number,'') AS wa_number,
              COALESCE(plan,'')      AS plan,
              COALESCE(credits,0)    AS credits
            FROM clients
            WHERE LOWER(COALESCE(name,'')) LIKE LOWER(:namepref)
               OR REPLACE(COALESCE(wa_number,''), '+','') LIKE :wapref
            ORDER BY COALESCE(name,''), id
            LIMIT :lim OFFSET :off
        """), {
            "namepref": f"{q}%",
            "wapref": f"{q.lstrip('+')}%",
            "lim": int(limit),
            "off": int(offset),
        }).mappings().all()
        return [dict(r) for r in rows]
