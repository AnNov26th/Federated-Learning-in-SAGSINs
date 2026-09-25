
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
