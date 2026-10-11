from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class FLExperimentCreate(BaseModel):
    scenario_id: Optional[int] = Field(default=None, ge=1)
    algorithm: Literal["FedAvg", "Centralized"] = "FedAvg"
    rounds: int = Field(default=3, ge=1, le=100)
    client_count: int = Field(default=5, ge=2, le=50)
    local_epochs: int = Field(default=1, ge=1, le=20)
    learning_rate: float = Field(default=0.01, gt=0, le=1)
    batch_size: int = Field(default=64, ge=8, le=512)
    partition: Literal["iid", "non_iid"] = "iid"
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    network_profile: Literal["normal", "high_latency", "low_bandwidth"] = "normal"
    dropout_probability: float = Field(default=0.0, ge=0, le=0.95)
    timeout_ms: int = Field(default=30_000, ge=10, le=120_000)


class FLExperimentSummary(BaseModel):
    id: int
    scenario_id: int
    algorithm: str
    status: str
    target_rounds: int
    completed_rounds: int
    latest_accuracy: Optional[float] = None
    latest_loss: Optional[float] = None
    is_simulation: bool
    error_message: Optional[str] = None


class FLClientRoundResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    client_id: str
    status: str
    samples_used: int
    local_accuracy: Optional[float] = None
    local_loss: Optional[float] = None
    training_duration_s: float
    latency_ms: float
    communication_time_ms: float
    data_transferred_mb: float
    failure_reason: Optional[str] = None


class FLRoundResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    round: int
    accuracy: float
    loss: float
    participants_count: int
    selected_count: int
    dropped_count: int
    round_duration_s: float
    metrics: Optional[dict] = None
    clients: list[FLClientRoundResult]


class FLExperimentDetail(FLExperimentSummary):
    config: dict
    created_at: datetime
    rounds: list[FLRoundResult]
