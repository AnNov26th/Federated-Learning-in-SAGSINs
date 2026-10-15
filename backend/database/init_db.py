from backend.database.database import engine, Base

# Import all models here to ensure they are registered with Base before calling create_all
from backend.models.scenario import Scenario
from backend.models.network import Node, NetworkLink
from backend.models.participant import Participant
from backend.models.simulation import Experiment, FLRound, Metric, FLClientRound
from backend.models.network_learning import NetworkDataset, NetworkObservation, NetworkRoundEvaluation, NetworkRoundPrediction

def init_db(bind=None):
    print("Creating database tables...")
    Base.metadata.create_all(bind=bind if bind is not None else engine)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()
