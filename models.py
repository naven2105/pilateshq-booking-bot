# models.py
from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from db import Base

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    wa_number = Column(String(32), nullable=False, unique=True, index=True)  # e.g., "27843131635"
    name = Column(String(120), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("wa_number", name="uq_clients_wa_number"),
    )
