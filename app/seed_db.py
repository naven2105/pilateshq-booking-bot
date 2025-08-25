# app/seed_db.py
# run once via Render shell or locally with DATABASE_URL set
"""
Seed convenience: inserts demo clients and generates 30 days of hourly sessions.
Usage on Render shell:
  python -m app.seed_db
"""
from datetime import date, timedelta, time
from sqlalchemy import text
from .db import get_session

def upsert_clients():
    demo = [
        # wa_number, name, plan, birthday_day, birthday_month, medical_notes, notes, household_id
        ("+27843131635","Nadine Example","2x",15,5,"Lower back pain","prefers mornings",None),
        ("+27840000001","Priya S","2x",12,5,"","duo + occasional single",2001),
        ("+27840000002","Raj S","2x",19,3,"","duo partner",2001),
        ("+27840000009","Emma T","2x",18,6,"","prefers peak",2005),
        ("+27840000020","Qinisela H","2x",10,8,"","group + occasional single",None),
        ("+27840000051","Vuyo S","3x",16,2,"","",None),
    ]
    with get_session() as s:
        for wa, name, plan, bday, bmon, med, notes, hh in demo:
            s.execute(text("""
                INSERT INTO clients (wa_number, name, plan, birthday_day, birthday_month, medical_notes, notes, household_id)
                VALUES (:wa, :name, :plan, :bday, :bmon, :med, :notes, :hh)
                ON CONFLICT (wa_number) DO UPDATE
                SET name = EXCLUDED.name,
                    plan = EXCLUDED.plan,
                    birthday_day = EXCLUDED.birthday_day,
                    birthday_month = EXCLUDED.birthday_month,
                    medical_notes = EXCLUDED.medical_notes,
                    notes = EXCLUDED.notes,
                    household_id = EXCLUDED.household_id
            """), {"wa": wa, "name": name, "plan": plan, "bday": bday, "bmon": bmon,
                   "med": med, "notes": notes, "hh": hh})

def seed_sessions(days: int = 30):
    """
    Create hourly sessions for the next `days`, 07:00–11:00 and 16:00–18:00 weekdays,
    and 07:00–11:00 on Saturdays. Sundays closed.
    """
    start = date.today()
    with get_session() as s:
        for d in (start + timedelta(n) for n in range(days)):
            dow = d.weekday()  # 0=Mon … 6=Sun
            if dow == 6:  # Sunday closed
                continue
            slots = []
            # Morning slots for all open days
            for hr in range(7, 12):   # 07:00–11:00
                slots.append(time(hr, 0))
            # Evening slots on Mon–Fri only
            if dow <= 4:
                for hr in (16, 17, 18):
                    slots.append(time(hr, 0))
            for t in slots:
                s.execute(text("""
                    INSERT INTO sessions (session_date, start_time, capacity, booked_count, status)
                    VALUES (:d, :t, :cap, 0, 'open')
                    ON CONFLICT (session_date, start_time) DO NOTHING
                """), {"d": d, "t": t, "cap": 6})

def simulate_demand():
    """Mark a few sessions as partially booked for realism."""
    with get_session() as s:
        s.execute(text("""
            UPDATE sessions
            SET booked_count = LEAST(capacity, 3)
            WHERE session_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
              AND start_time IN ('07:00','08:00','17:00')
        """))

if __name__ == "__main__":
    upsert_clients()
    seed_sessions(days=30)
    simulate_demand()
    print("✅ Seed complete.")
