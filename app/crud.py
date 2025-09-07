# app/crud.py
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa

def upsert_public_client(wa_number: str, name: str | None):
    """
    Ensure a client row exists for this WA number.
    - If name is provided and non-empty => update name.
    - If name is missing/empty => insert a safe placeholder to satisfy NOT NULL.
    Returns dict(id, name, wa_number).
    """
    wa_norm = normalize_wa(wa_number)
    nm_in = (name or "").strip()

    # Build a friendly placeholder like: "Guest 4607" based on WA last 4 digits
    last4 = wa_norm[-4:] if wa_norm and len(wa_norm) >= 4 else "0000"
    placeholder = f"Guest {last4}"

    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (name, wa_number, credits, plan)
                VALUES (COALESCE(NULLIF(:name, ''), :placeholder), :wa, 0, NULL)
                ON CONFLICT (wa_number)
                DO UPDATE SET
                    -- Only overwrite if a new non-empty name is provided
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), clients.name)
                RETURNING id, name, wa_number
            """),
            {
                "name": nm_in,                 # could be '' (empty)
                "placeholder": placeholder,    # used if name is empty/missing
                "wa": wa_norm,
            },
        ).mappings().first()
        return dict(row) if row else None
