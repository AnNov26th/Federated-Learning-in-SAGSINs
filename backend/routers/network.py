
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from backend.database.database import get_db
from backend.models.network import Node
from backend.schemas.network import Node as NodeSchema, NodeCreate
from backend.schemas.base import APIResponse

router = APIRouter()

@router.get("/nodes", response_model=APIResponse[List[NodeSchema]])
def get_nodes(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()
    return APIResponse(data=nodes)

@router.post("/nodes", response_model=APIResponse[NodeSchema])
def create_node(node: NodeCreate, db: Session = Depends(get_db)):
    db_node = Node(**node.model_dump())
    db.add(db_node)
    try:
        db.commit()
        db.refresh(db_node)
        return APIResponse(data=db_node)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
