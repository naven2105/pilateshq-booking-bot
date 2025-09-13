# app/models.py
from sqlalchemy import Column, Integer, String, Date, Time, ForeignKey
from sqlalchemy.orm import relationship
from .db import Base

class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    wa_number = Column(String, unique=True, nullable=True)
    package_type = Column(String, nullable=True)  # single | duo | trio

    bookings = relationship("Booking", back_populates="client")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    capacity = Column(Integer, default=1)
    booked_count = Column(Integer, default=0)
    status = Column(String, default="scheduled")  # scheduled | cancelled | completed

    bookings = relationship("Booking", back_populates="session")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    status = Column(String, default="confirmed")  # confirmed | cancelled

    client = relationship("Client", back_populates="bookings")
    session = relationship("Session", back_populates="bookings")


class Pricing(Base):
    __tablename__ = "pricing"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String, unique=True, nullable=False)
    price = Column(Integer, nullable=False)
