
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
