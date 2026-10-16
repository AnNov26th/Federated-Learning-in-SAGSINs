from typing import Literal

from pydantic import BaseModel, Field


class EventRouteRequest(BaseModel):
    scenario_id: int = Field(ge=1)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    service: Literal["Message", "Video Call", "Watch Video", "Gaming", "Emergency"] = "Message"
    policy: Literal["predictive", "static"] = "predictive"
    topology: Literal["configured", "estimated"] = "configured"
    experiment_id: int | None = Field(default=None, ge=1)
    target_id: str | None = Field(default=None, max_length=50)
    access_radius_km: float = Field(default=1500, gt=0, le=5000, allow_inf_nan=False)
    load_ratio: float = Field(default=.35, ge=0, le=.94, allow_inf_nan=False)
