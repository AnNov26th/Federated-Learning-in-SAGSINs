"""Additive tables for generated network data and federated regression audits."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint

from backend.database.database import Base


class NetworkDataset(Base):
    __tablename__ = "network_datasets"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    seed = Column(Integer, nullable=False)
    generator_version = Column(String(50), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    config_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class NetworkObservation(Base):
    __tablename__ = "network_observations"
    __table_args__ = (UniqueConstraint("dataset_id", "client_id", "sequence", name="uq_network_observation"),)

    id = Column(Integer, primary_key=True)
    dataset_id = Column(Integer, ForeignKey("network_datasets.id"), nullable=False, index=True)
    client_id = Column(String(50), ForeignKey("nodes.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    split = Column(String(12), nullable=False)  # train, validation, online, test
    features_json = Column(JSON, nullable=False)
    target_delay_ms = Column(Float, nullable=False)  # next tick's model round-trip transfer


class NetworkRoundEvaluation(Base):
    __tablename__ = "network_round_evaluations"

    round_id = Column(Integer, ForeignKey("fl_rounds.id"), primary_key=True)
    mae_ms = Column(Float, nullable=False)
    rmse_ms = Column(Float, nullable=False)
    r2 = Column(Float, nullable=True)
    validation_mae_ms = Column(Float, nullable=False)
    persistence_mae_ms = Column(Float, nullable=False)
    test_samples = Column(Integer, nullable=False)
    selection_source = Column(String(40), nullable=False)
    checkpoint_json = Column(JSON, nullable=False)


class NetworkRoundPrediction(Base):
    __tablename__ = "network_round_predictions"
    __table_args__ = (UniqueConstraint("round_id", "client_id", name="uq_network_round_prediction"),)

    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("fl_rounds.id"), nullable=False, index=True)
    client_id = Column(String(50), ForeignKey("nodes.id"), nullable=False)
    observation_id = Column(Integer, ForeignKey("network_observations.id"), nullable=False)
    predicted_delay_ms = Column(Float, nullable=False)
    observed_delay_ms = Column(Float, nullable=True)
    rule_delay_ms = Column(Float, nullable=False)
    selected = Column(Boolean, nullable=False)
    model_round = Column(Integer, nullable=False)
