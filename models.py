# models.py
from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, ForeignKey, UniqueConstraint,
    Enum, Index, Text
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
import enum
from db import Base

class BookingStatus(str, enum.Enum):
    proposed = "proposed"     # client submitted request
    approved = "approved"     # Nadine approved (soft-reserved)
    reserved = "reserved"     # tentatively held (capacity hidden)
    confirmed = "confirmed"   # final (paid/locked)
    declined = "declined"
    cancelled = "cancelled"
    expired = "expired"

class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)          # "2784..."
    name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    plan: Mapped[str] = mapped_column(String(16), default="1x", nullable=False)          # "1x"/"2x"/"3x"
    household_id: Mapped[int | None] = mapped_column(Integer, index=True)
    birthday_day: Mapped[int | None] = mapped_column(Integer)                             # 1..31
    birthday_month: Mapped[int | None] = mapped_column(Integer)                           # 1..12
    medical_notes: Mapped[str | None] = mapped_column(Text)                               # sensitive; minimal access
    notes: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ClassType(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True)                            # GROUP/DUO/SINGLE
    title: Mapped[str] = mapped_column(String(64))
    capacity: Mapped[int] = mapped_column(Integer, default=6, nullable=False)

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), index=True)
    start_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)
    capacity_left: Mapped[int] = mapped_column(Integer, nullable=False)                   # decremented on reserve/confirm
    peak: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gcal_event_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("class_id","start_at", name="uq_session_slot"),)

class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.proposed, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))          # e.g., +48h
    __table_args__ = (UniqueConstraint("client_id","session_id", name="uq_proposal_once"),)

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.confirmed, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("client_id","session_id", name="uq_booking_once"),)

class Waitlist(Base):
    __tablename__ = "waitlist"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("session_id","client_id", name="uq_waitlist_once"),)

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))                                         # reminder_1h, reminder_1d, monthly, slot_open
    next_run_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# Helpful indexes
Index("ix_sessions_start_peak", Session.start_at, Session.peak)
Index("ix_proposals_status_created", Proposal.status, Proposal.created_at)
Index("ix_bookings_status", Booking.status)
