
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
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

class Node(NodeBase):
    class Config:
        from_attributes = True
