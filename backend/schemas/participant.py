
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

class ParticipantBase(BaseModel):
    node_id: str
    dataset_size: int = Field(ge=0)
    local_epochs: int = Field(ge=1)
    selected: bool = False

class ParticipantCreate(ParticipantBase):
    pass

class Participant(ParticipantBase):
    model_config = ConfigDict(from_attributes=True)
    id: int

class ParticipantUpdate(BaseModel):
    selected: Optional[bool] = None
    local_epochs: Optional[int] = Field(default=None, ge=1)
