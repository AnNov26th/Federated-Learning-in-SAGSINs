from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from backend.database.database import get_db
from backend.schemas.base import APIResponse
from backend.services.research_region_service import (
    create_region,
    region_for,
    set_conditions,
)
from backend.services.research_flow_service import advance_region
from backend.routers.routing import _lock_scenario

router = APIRouter()


def summary(region):
    return {
        "scenario_id": region.scenario_id,
        "sim_time_s": region.sim_time_s,
        "running": region.running,
        **region.config_json,
    }


@router.post("/region", status_code=201)
def provision(db: Session = Depends(get_db)):
    region = create_region(db)
    db.commit()
    return APIResponse(data=summary(region))


@router.get("/{scenario_id}")
def state(scenario_id: int, db: Session = Depends(get_db)):
    region = region_for(db, scenario_id)
    if not region:
        raise HTTPException(404, "Not a research scenario")
    return APIResponse(data=summary(region))


class Control(BaseModel):
    conditions: (
        Literal[
            "normal",
            "congested",
            "terrestrial_failure",
            "satellite_fallback",
            "disconnected",
        ]
        | None
    ) = None
    running: bool | None = None
    advance_s: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)


@router.post("/{scenario_id}/control")
def control(scenario_id: int, request: Control, db: Session = Depends(get_db)):
    _lock_scenario(db, scenario_id)
    region = region_for(db, scenario_id)
    if not region:
        raise HTTPException(404, "Not a research scenario")
    if request.conditions is not None:
        set_conditions(region, request.conditions)
    if request.running is not None:
        region.running = request.running
    # A zero step applies a fault/retries waiting flows at exactly this instant.
    advance_region(db, region, request.advance_s)
    db.commit()
    return APIResponse(data=summary(region))
