from backend.database.database import engine, Base

# Import all models here to ensure they are registered with Base before calling create_all
from backend.models.scenario import Scenario
from backend.models.network import Node, NetworkLink
from backend.models.routing_event import RoutingEvent
from backend.models.participant import Participant
from backend.models.simulation import Experiment, FLRound, Metric, FLClientRound
from backend.models.network_learning import NetworkDataset, NetworkObservation, NetworkRoundEvaluation, NetworkRoundPrediction
from backend.database.migrations import DatabaseMigration, apply_data_migrations

def init_db(bind=None):
    target = bind if bind is not None else engine
    print("Creating database tables...")
    Base.metadata.create_all(bind=target)
    from backend.database.routing_migrations import migrate_routing_events
    migrate_routing_events(target)
    from backend.database.seed_db import migrate_node_metadata
    migrate_node_metadata(bind=target)
    apply_data_migrations(target)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()
