from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from backend.database.database import Base
from datetime import datetime, timezone

class Node(Base):
    __tablename__ = "nodes"

    id = Column(String(50), primary_key=True, index=True) # e.g., SAT-01, UAV-01
    type = Column(String(20), nullable=False) # SPACE, AIR, GROUND, SEA
    lat = Column(Float, nullable=False, default=0.0) # Latitude
    lng = Column(Float, nullable=False, default=0.0) # Longitude
    alt = Column(Float, nullable=False, default=0.0) # Altitude (km)
    bandwidth = Column(Float, nullable=False) # Mbps
    latency = Column(Float, nullable=False) # ms
    battery_percent = Column(Float, nullable=False, default=100.0) # %
    status = Column(String(20), default="ACTIVE") # ACTIVE, INACTIVE, OFFLINE, FAILED
    last_heartbeat = Column(DateTime, nullable=True)

class NetworkLink(Base):
    __tablename__ = "network_links"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), ForeignKey("nodes.id"), nullable=False)
    target = Column(String(50), ForeignKey("nodes.id"), nullable=False)
    distance = Column(Float, nullable=False) # km
    bandwidth = Column(Float, nullable=False) # Mbps
    latency = Column(Float, nullable=False) # ms
    status = Column(String(20), default="ACTIVE")
    last_heartbeat = Column(DateTime, nullable=True)
