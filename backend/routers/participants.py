
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from backend.database.database import get_db
from backend.models.participant import Participant
from backend.schemas.participant import Participant as ParticipantSchema, ParticipantCreate
from backend.schemas.base import APIResponse

router = APIRouter()

@router.get("/", response_model=APIResponse[List[ParticipantSchema]])
def get_participants(db: Session = Depends(get_db)):
    parts = db.query(Participant).all()
    return APIResponse(data=parts)

@router.post("/", response_model=APIResponse[ParticipantSchema])
def create_participant(p: ParticipantCreate, db: Session = Depends(get_db)):
    db_p = Participant(**p.model_dump())
    db.add(db_p)
    try:
        db.commit()
        db.refresh(db_p)
        return APIResponse(data=db_p)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
