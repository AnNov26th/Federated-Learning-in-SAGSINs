from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class EventRouteRequest(BaseModel):
    allocation_policy: Literal["equal", "demand", "minimax", "deadline"] = "deadline"
    scenario_id: int = Field(ge=1)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    service: Literal["Message", "Video Call", "Watch Video", "Gaming", "Emergency"] = "Message"
    source_device: Literal["network_gateway", "auto", "smartphone", "emergency_radio", "satellite_terminal", "iot_sensor", "legacy_simulator"] = "auto"
    policy: Literal["predictive", "static"] = "predictive"
    topology: Literal["configured", "estimated", "adaptive"] = "adaptive"
    experiment_id: int | None = Field(default=None, ge=1)
    target_id: str | None = Field(default=None, max_length=50)
    routing_scope: Literal["local", "global"] = "local"
    local_radius_km: float = Field(default=300, gt=0, le=20040, allow_inf_nan=False)
    # Additional ingress limit; local scope also bounds all nodes and hops.
    access_radius_km: float | None = Field(default=None, gt=0, le=20040, allow_inf_nan=False)
    required_bandwidth_mbps: float | None = Field(default=None, gt=0, le=1000000, allow_inf_nan=False)
    load_ratio: float = Field(default=.35, ge=0, le=.94, allow_inf_nan=False)
    allow_load_reduction: bool = False
    auto_train: bool = False
    allow_reposition: bool = False
    mobility_boost: float = Field(default=2, ge=1, le=5, allow_inf_nan=False)
    duration_s: float = Field(default=60, gt=0, le=86400, allow_inf_nan=False)
    wait_timeout_s: float = Field(default=30, gt=0, le=86400, allow_inf_nan=False)


class SavedEventRequest(EventRouteRequest):
    client_key: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)


class EventPlaybackUpdate(BaseModel):
    snapshot_at: str = Field(max_length=64)
    elapsed_s: float = Field(ge=0, allow_inf_nan=False)
    paused: bool = False
