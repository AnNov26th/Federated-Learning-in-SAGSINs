from sqlalchemy import Column, Integer, String, Float, ForeignKey
from backend.database.database import Base

class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    algorithm = Column(String(50), nullable=False) # FedAvg, FedProx
    rounds = Column(Integer, nullable=False)
    learning_rate = Column(Float, nullable=False)

class FLRound(Base):
    __tablename__ = "fl_rounds"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    round = Column(Integer, nullable=False)
    participants_count = Column(Integer, nullable=False)
    accuracy = Column(Float, nullable=False)
    loss = Column(Float, nullable=False)
    time = Column(Float, nullable=False) # seconds

class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(Integer, ForeignKey("fl_rounds.id"), nullable=False)
    latency = Column(Float, nullable=False)
    communication_time = Column(Float, nullable=False)
    energy_consumption = Column(Float, nullable=False)
    bandwidth_usage = Column(Float, nullable=False)
    data_transferred = Column(Float, nullable=False)
    packet_loss = Column(Float, nullable=False)
