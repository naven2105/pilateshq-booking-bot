# app/models.py
# app/models.py (optional ORM mappings; not required by current code but useful later)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Date, Time

class Base(DeclarativeBase):
    pass

class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int]           = mapped_column(primary_key=True)
    wa_number: Mapped[str]    = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str]         = mapped_column(String(120), nullable=False, default="")
    plan: Mapped[str]         = mapped_column(String(16), nullable=False, default="1x")
    birthday_day: Mapped[int | None]   = mapped_column(Integer, nullable=True)
    birthday_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    medical_notes: Mapped[str | None]  = mapped_column(Text, nullable=True)
    notes: Mapped[str | None]          = mapped_column(String(500), nullable=True)
    household_id: Mapped[int | None]   = mapped_column(Integer, nullable=True)

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int]           = mapped_column(primary_key=True)
    session_date: Mapped[Date]
    start_time:   Mapped[Time]
    capacity:     Mapped[int]
    booked_count: Mapped[int]
    status:       Mapped[str]    # 'open' | 'full' | 'closed'
    notes:        Mapped[str | None]
