from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FLExperimentCreate(BaseModel):
    scenario_id: Optional[int] = Field(default=None, ge=1)
    algorithm: Literal["FedAvg", "DelayAware", "Predictive", "Centralized"] = "FedAvg"
    task: Literal["mnist", "network_delay"] = "mnist"
    dataset_id: Optional[int] = Field(default=None, ge=1)
    samples_per_client: int = Field(default=160, ge=40, le=2000)
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

    @model_validator(mode="after")
    def validate_task(self):
        if self.algorithm == "Predictive" and self.task != "network_delay":
            raise ValueError("Predictive scheduling requires the network_delay task.")
        if self.dataset_id is not None and self.task != "network_delay":
            raise ValueError("A network dataset can only be used for network_delay.")
        return self


class FLComparisonCreate(BaseModel):
    scenario_id: Optional[int] = Field(default=None, ge=1)
    task: Literal["mnist", "network_delay"] = "mnist"
    dataset_id: Optional[int] = Field(default=None, ge=1)
    samples_per_client: int = Field(default=160, ge=40, le=2000)
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

    @model_validator(mode="after")
    def validate_dataset_task(self):
        if self.dataset_id is not None and self.task != "network_delay":
            raise ValueError("A network dataset can only be used for network_delay.")
        return self


class FLExperimentSummary(BaseModel):
    id: int
    scenario_id: int
    algorithm: str
    status: str
    target_rounds: int
    completed_rounds: int
    latest_accuracy: Optional[float] = None
    latest_loss: Optional[float] = None
    task: str = "mnist"
    dataset_id: Optional[int] = None
    latest_mae_ms: Optional[float] = None
    latest_rmse_ms: Optional[float] = None
    latest_r2: Optional[float] = None
    is_simulation: bool
    error_message: Optional[str] = None
    actual_duration_s: Optional[float] = None


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
    accuracy: Optional[float] = None
    loss: float
    participants_count: int
    selected_count: int
    dropped_count: int
    aggregated: bool = True
    status: str = "COMPLETED"
    round_duration_s: float
    metrics: Optional[dict] = None
    clients: list[FLClientRoundResult]
    prediction_metrics: Optional[dict] = None
    predictions: list[dict] = Field(default_factory=list)


class FLExperimentDetail(FLExperimentSummary):
    config: dict
    created_at: datetime
    rounds: list[FLRoundResult]
