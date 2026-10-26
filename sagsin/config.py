from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

FEATURE_VERSION = "application-link-v2"
TARGET = "next_tick_reference_payload_delay_ms"
SIMULATOR_VERSION = "fluid-shared-link-v3-deadlines"


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    seed: int = Field(42, ge=0, le=2**31 - 1)
    model_family: Literal["residual_mlp", "trend"] = "trend"
    transport_codec: Literal["json", "packed"] = "packed"
    optimizer: Literal["auto", "sgd", "adam"] = "auto"
    loss: Literal["auto", "mse", "huber"] = "auto"
    reroute_interval: int = Field(3, ge=1, le=30)
    reroute_improvement: float = Field(0.15, ge=0, le=1)
    client_count: int = Field(4, ge=1)
    client_ids: list[str] | None = None
    clients_per_round: int | None = Field(None, ge=1)
    max_workers: int = Field(4, ge=1, le=16)
    topology: dict | None = None
    local_epochs_by_client: dict[str, int] = {}
    rounds: int = Field(5, ge=1)
    samples_per_client: int = Field(240, ge=40)
    client_fraction: float = Field(1.0, gt=0, le=1)
    local_epochs: int = Field(2, ge=1)
    batch_size: int = Field(32, ge=1)
    learning_rate: float = Field(0.02, gt=0)
    profile: str = Field("mixed", pattern="^(normal|mixed|congested)$")
    partition: str = Field("non_iid", pattern="^(iid|non_iid)$")
    selection: str = Field("random", pattern="^(random|delay_aware|predictive)$")
    dropout_probability: float = Field(0.0, ge=0, le=1)
    timeout_s: float = Field(90, gt=0)
    network_ticks: int = Field(60, ge=20, le=300)
    flow_count: int = Field(18, ge=4, le=100)
    payload_bytes: int = Field(65536, ge=256, le=1048576)

    @classmethod
    def from_saved(cls, value):
        """Preserve old experiment/model choices when reading legacy records."""
        return cls(**dict({"model_family":"residual_mlp", "transport_codec":"json"}, **value))
