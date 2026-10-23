"""Saved simulation events and their bandwidth reservations."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String

from backend.database.database import Base


class RoutingEvent(Base):
    __tablename__ = "routing_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True)
    client_key = Column(String(64), nullable=False, unique=True)
    display_number = Column(Integer, nullable=False)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False, index=True)
    service = Column(String(30), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    config_json = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=False)
    playback_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
