# app/models.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Time,
    ForeignKey,
    DateTime,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .db import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    wa_number = Column(String(20), unique=True, nullable=True)
    phone = Column(String(20), unique=True, nullable=True)
    package_type = Column(String(16), nullable=True)  # single | duo | group | test
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    bookings = relationship("Booking", back_populates="client", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="client", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="client", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    capacity = Column(Integer, default=1)
    booked_count = Column(Integer, default=0)
    status = Column(String, default="open")  # open | full | cancelled | completed

    bookings = relationship("Booking", back_populates="session", cascade="all, delete-orphan")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, default="confirmed")  # confirmed | active | cancelled | sick | no_show
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="bookings")
    session = relationship("Session", back_populates="bookings")


class Pricing(Base):
    __tablename__ = "pricing"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String, unique=True, nullable=False)
    price = Column(Integer, nullable=False)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    wa_number = Column(String(20), unique=True, nullable=False)
    name = Column(String(120), nullable=True)
    interest = Column(String(32), nullable=True)  # taster | group | private
    status = Column(String, default="new")        # new | converted | lost
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    last_contact = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    client = relationship("Client", back_populates="leads")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(32), nullable=False)  # daily | tomorrow | weekly
    next_run_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="notifications")
