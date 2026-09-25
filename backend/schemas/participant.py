
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
