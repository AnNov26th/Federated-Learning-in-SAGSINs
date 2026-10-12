
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional
from datetime import datetime

class NodeBase(BaseModel):
    id: str
    type: str
    lat: float
    lng: float
    alt: float
    bandwidth: float
    latency: float
    battery_percent: float = 100.0
    status: str = "ACTIVE"
    last_heartbeat: Optional[datetime] = None
    scenario_id: Optional[int] = None
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    continent: Optional[str] = None
    land_area_km2: Optional[float] = None
    location_name: Optional[str] = None
    coordinate_source: Optional[str] = None
    is_simulated: bool = False
    platform: Optional[str] = None
    orbit_inclination_deg: Optional[float] = None
    orbit_plane: Optional[int] = None
    orbit_phase_deg: Optional[float] = None
    epoch_utc: Optional[str] = None

class NodeCreate(NodeBase):
    pass

class NodeUpdate(BaseModel):
    status: Optional[Literal["ACTIVE", "INACTIVE", "OFFLINE", "FAILED"]] = None
    bandwidth: Optional[float] = Field(default=None, gt=0)
    latency: Optional[float] = Field(default=None, ge=0)
    battery_percent: Optional[float] = Field(default=None, ge=0, le=100)

class NetworkLinkCreate(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    bandwidth: float = Field(gt=0)
    latency: float = Field(ge=0)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"

class NetworkLinkUpdate(BaseModel):
    status: Literal["ACTIVE", "INACTIVE"]

class Node(NodeBase):
    model_config = ConfigDict(from_attributes=True)
