from sqlalchemy import Column, Integer, String
from backend.database.database import Base

class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    total_nodes = Column(Integer, default=0)
    space = Column(Integer, default=0)
    air = Column(Integer, default=0)
    ground = Column(Integer, default=0)
    sea = Column(Integer, default=0)
