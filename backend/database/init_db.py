from backend.database.database import engine, Base

# Import all models here to ensure they are registered with Base before calling create_all
from backend.models.scenario import Scenario
from backend.models.network import Node, NetworkLink
from backend.models.participant import Participant
from backend.models.simulation import Experiment, FLRound, Metric

def init_db():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()
