import os

def create_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

schemas_network = """
from pydantic import BaseModel
from typing import Optional

class NodeBase(BaseModel):
    id: str
    type: str
    lat: float
    lng: float
    alt: float
    bandwidth: float
    latency: float
    battery_percent: float = 100.0

class NodeCreate(NodeBase):
    pass

class Node(NodeBase):
    class Config:
        from_attributes = True
"""
create_file('backend/schemas/network.py', schemas_network)

routers_network = """
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
"""
create_file('backend/routers/network.py', routers_network)

schemas_participants = """
from pydantic import BaseModel
from typing import Optional

class ParticipantBase(BaseModel):
    node_id: str
    dataset_size: int
    local_epochs: int
    selected: bool = False

class ParticipantCreate(ParticipantBase):
    pass

class Participant(ParticipantBase):
    id: int
    class Config:
        from_attributes = True
"""
create_file('backend/schemas/participant.py', schemas_participants)

routers_participants = """
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
"""
create_file('backend/routers/participants.py', routers_participants)

schemas_simulation = """
from pydantic import BaseModel
from typing import Optional

class ScenarioBase(BaseModel):
    name: str
    total_nodes: int = 0
    space: int = 0
    air: int = 0
    ground: int = 0
    sea: int = 0

class ScenarioCreate(ScenarioBase):
    pass

class Scenario(ScenarioBase):
    id: int
    class Config:
        from_attributes = True
"""
create_file('backend/schemas/simulation.py', schemas_simulation)

routers_simulations = """
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
"""
create_file('backend/routers/simulations.py', routers_simulations)

print("Created all files.")
