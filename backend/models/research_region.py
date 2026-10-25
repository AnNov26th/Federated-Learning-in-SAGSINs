"""Isolated regional experiments; does not alter the global inventory."""

from sqlalchemy import Column, Integer, Float, Boolean, ForeignKey, JSON
from backend.database.database import Base


class ResearchRegion(Base):
    __tablename__ = "research_regions"
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), primary_key=True)
    sim_time_s = Column(Float, nullable=False, default=0)
    running = Column(Boolean, nullable=False, default=False)
    config_json = Column(JSON, nullable=False)
