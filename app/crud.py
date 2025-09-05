def find_next_upcoming_booking_by_wa(wa_number: str):
    """
    Return the next upcoming booking (soonest future session) for this WA number,
    or None if not found.
    """
    from .utils import normalize_wa
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT b.id AS booking_id,
                   s.id AS session_id,
                   s.session_date,
                   s.start_time,
                   c.id AS client_id,
                   c.name,
                   c.wa_number
            FROM bookings b
            JOIN sessions s ON s.id = b.session_id
            JOIN clients  c ON c.id = b.client_id
            , now_local
            WHERE c.wa_number = :wa
              AND b.status = 'confirmed'
              AND (s.session_date + s.start_time) > now_local.ts
            ORDER BY s.session_date, s.start_time
            LIMIT 1
        """), {"wa": wa}).mappings().first()
        return dict(row) if row else None
