"""Service endpoints are separate from Node and the FL participant pool."""
from sqlalchemy import Column, Float, Double, Boolean, ForeignKey, Integer, JSON, String
from backend.database.database import Base


class ServiceClient(Base):
    __tablename__ = 'service_clients'
    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey('scenarios.id'), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    device = Column(String(30), nullable=False)
    token = Column(String(64), nullable=False)
    # MySQL FLOAT cannot resolve a 35-second lease at today's Unix epoch.
    last_seen = Column(Double, nullable=False, default=0)
    deleted = Column(Boolean, nullable=False, default=False, server_default='0')


class ServiceSession(Base):
    __tablename__ = 'service_sessions'
    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey('scenarios.id'), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey('service_clients.id'), nullable=False)
    target_id = Column(Integer, ForeignKey('service_clients.id'), nullable=True)
    service = Column(String(30), nullable=False)
    state = Column(String(30), nullable=False)
    config_json = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=False)
