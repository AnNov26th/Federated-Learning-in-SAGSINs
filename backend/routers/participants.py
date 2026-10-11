
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from backend.database.database import get_db
from backend.models.network import Node
from backend.models.participant import Participant
from backend.schemas.participant import Participant as ParticipantSchema, ParticipantCreate, ParticipantUpdate
from backend.schemas.base import APIResponse

router = APIRouter()

@router.get("/", response_model=APIResponse[List[ParticipantSchema]])
def get_participants(db: Session = Depends(get_db)):
    parts = db.query(Participant).all()
    return APIResponse(data=parts)

@router.post("/", response_model=APIResponse[ParticipantSchema])
def create_participant(p: ParticipantCreate, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == p.node_id).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found.")
    if p.selected and str(node.status).upper() != "ACTIVE":
        raise HTTPException(status_code=400, detail="Only ACTIVE nodes can be selected for FL.")
    if db.query(Participant).filter(Participant.node_id == p.node_id).first():
        raise HTTPException(status_code=409, detail="This node already has a participant record.")
    db_p = Participant(**p.model_dump())
    db.add(db_p)
    try:
        db.commit()
        db.refresh(db_p)
        return APIResponse(data=db_p)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{participant_id}", response_model=APIResponse[ParticipantSchema])
def update_participant(participant_id: int, changes: ParticipantUpdate, db: Session = Depends(get_db)):
    participant = db.query(Participant).filter(Participant.id == participant_id).first()
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found.")
    updates = changes.model_dump(exclude_unset=True)
    if any(value is None for value in updates.values()):
        raise HTTPException(status_code=422, detail="Participant fields cannot be set to null.")
    if updates.get("selected") is True:
        node = db.query(Node).filter(Node.id == participant.node_id).first()
        if node is None or str(node.status).upper() != "ACTIVE":
            raise HTTPException(status_code=400, detail="Only ACTIVE nodes can be selected for FL.")
    for field, value in updates.items():
        setattr(participant, field, value)
    db.commit()
    db.refresh(participant)
    return APIResponse(data=participant)
