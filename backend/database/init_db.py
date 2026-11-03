from backend.database.database import engine, Base

# Import all models here to ensure they are registered with Base before calling create_all
from backend.models.scenario import Scenario
from backend.models.network import Node, NetworkLink
from backend.models.routing_event import RoutingEvent
from backend.models.service_session import ServiceClient, ServiceSession
from backend.models.research_region import ResearchRegion
from backend.models.participant import Participant
from backend.models.simulation import Experiment, FLRound, Metric, FLClientRound
from backend.models.network_learning import NetworkDataset, NetworkObservation, NetworkRoundEvaluation, NetworkRoundPrediction
from backend.database.migrations import DatabaseMigration, apply_data_migrations

def init_db(bind=None):
    target = bind if bind is not None else engine
    print("Creating database tables...")
    from backend.database.storage_health import inspect_legacy_store
    unavailable = inspect_legacy_store(target)
    tables = [table for table in Base.metadata.sorted_tables if table.name not in unavailable]
    # Do not reflect, drop or recreate the unreadable legacy table.
    Base.metadata.create_all(bind=target, tables=tables)
    # Add simulator deletion state without dropping client/session audit data.
    from sqlalchemy import inspect, text
    service_columns = inspect(target).get_columns('service_clients')
    if not any(c['name'] == 'deleted' for c in service_columns):
        with target.begin() as connection:
            connection.execute(text('ALTER TABLE service_clients ADD COLUMN deleted BOOLEAN NOT NULL DEFAULT 0'))
    if target.dialect.name == 'mysql':
        heartbeat = next(c for c in service_columns if c['name'] == 'last_seen')
        if str(heartbeat['type']).upper() == 'FLOAT':
            with target.begin() as connection:
                connection.execute(text('ALTER TABLE service_clients MODIFY COLUMN last_seen DOUBLE NOT NULL'))
    from backend.database.routing_migrations import migrate_routing_events
    migrate_routing_events(target)
    from backend.database.seed_db import migrate_node_metadata
    migrate_node_metadata(bind=target)
    apply_data_migrations(target)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()
