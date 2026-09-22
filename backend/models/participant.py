from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from backend.database.database import Base

class Participant(Base):
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(String(50), ForeignKey("nodes.id"), nullable=False)
    dataset_size = Column(Integer, nullable=False)
    local_epochs = Column(Integer, nullable=False)
    selected = Column(Boolean, default=False)
