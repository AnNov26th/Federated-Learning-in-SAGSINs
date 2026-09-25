from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, JSON
from backend.database.database import Base
from datetime import datetime, timezone

class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    algorithm = Column(String(50), nullable=False) # FedAvg, FedProx
    rounds = Column(Integer, nullable=False)
    learning_rate = Column(Float, nullable=False)
    
    status = Column(String(20), default="QUEUED") # QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(String(500), nullable=True)
    is_simulation = Column(Boolean, default=True)
    config_json = Column(JSON, nullable=True)

class FLRound(Base):
    __tablename__ = "fl_rounds"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    round = Column(Integer, nullable=False)
    participants_count = Column(Integer, nullable=False)
    accuracy = Column(Float, nullable=False) # 0.0 - 1.0
    loss = Column(Float, nullable=False)
    round_duration_s = Column(Float, nullable=False) # seconds

class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(Integer, ForeignKey("fl_rounds.id"), nullable=False)
    latency_ms = Column(Float, nullable=False) # ms
    communication_time_ms = Column(Float, nullable=False) # ms
    energy_j = Column(Float, nullable=False) # Joules
    bandwidth_mbps = Column(Float, nullable=False) # Mbps
    data_transferred_mb = Column(Float, nullable=False) # MB
    packet_loss_ratio = Column(Float, nullable=False) # 0.0 - 1.0
