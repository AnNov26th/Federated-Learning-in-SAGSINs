from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenario_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    device: Literal['network_gateway', 'smartphone', 'satellite_terminal', 'emergency_radio', 'iot_sensor'] = 'network_gateway'


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    service: Literal['Video Call', 'Emergency', 'Message', 'Watch Video', 'Gaming']
    target_id: int | None = Field(None, ge=1)
    policy: Literal['static', 'current', 'predictive'] = 'static'
    experiment_id: int | None = Field(None, ge=1)
    wait_timeout_s: float = Field(30, ge=5, le=300, allow_inf_nan=False)
    reroute_interval_s: float = Field(3, ge=1, le=30)
    minimum_hold_s: float = Field(10, ge=0, le=120)
    reroute_improvement: float = Field(.15, ge=0, le=.9)
    max_path_stretch: float = Field(2, ge=1, le=5)
