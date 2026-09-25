
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from backend.database.database import get_db
from backend.models.scenario import Scenario
from backend.schemas.simulation import Scenario as ScenarioSchema, ScenarioCreate
from backend.schemas.base import APIResponse

router = APIRouter()

@router.get("/scenarios", response_model=APIResponse[List[ScenarioSchema]])
def get_scenarios(db: Session = Depends(get_db)):
    scenarios = db.query(Scenario).all()
    return APIResponse(data=scenarios)

@router.post("/scenarios", response_model=APIResponse[ScenarioSchema])
def create_scenario(sc: ScenarioCreate, db: Session = Depends(get_db)):
    db_sc = Scenario(**sc.model_dump())
    db.add(db_sc)
    try:
        db.commit()
        db.refresh(db_sc)
        return APIResponse(data=db_sc)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
