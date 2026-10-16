from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.models.scenario import Scenario
from backend.schemas.base import APIResponse
from backend.schemas.routing import EventRouteRequest
from backend.services.routing_service import model_candidates, model_summary, route_event

router = APIRouter()


@router.get("/context", response_model=APIResponse[dict])
def routing_context(db: Session = Depends(get_db)):
    return APIResponse(data={
        "scenarios": [{"id": s.id, "name": s.name} for s in db.query(Scenario).order_by(Scenario.id)],
        "models": [model_summary(candidate) for candidate in model_candidates(db)],
    })


@router.post("/event", response_model=APIResponse[dict])
def event_route(request: EventRouteRequest, db: Session = Depends(get_db)):
    if db.get(Scenario, request.scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    return APIResponse(data=route_event(db, request))
