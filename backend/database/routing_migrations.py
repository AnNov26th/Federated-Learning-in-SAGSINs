"""Upgrade saved-event schemas from earlier app versions without replacing rows."""
from uuid import uuid4

from sqlalchemy import inspect, text


def migrate_routing_events(bind):
    if not inspect(bind).has_table("routing_events"):
        return
    columns = {column["name"]: column for column in inspect(bind).get_columns("routing_events")}
    if "client_key" not in columns:
        # Add as nullable first so tables containing saved points can upgrade.
        with bind.begin() as connection:
            connection.execute(text("ALTER TABLE routing_events ADD COLUMN client_key VARCHAR(64) NULL"))
    if "display_number" not in columns:
        with bind.begin() as connection:
            connection.execute(text("ALTER TABLE routing_events ADD COLUMN display_number INTEGER NULL"))

    with bind.begin() as connection:
        connection.execute(text("UPDATE routing_events SET display_number = id WHERE display_number IS NULL"))
        missing = connection.execute(text(
            "SELECT id FROM routing_events WHERE client_key IS NULL OR client_key = ''"
        )).scalars().all()
        for event_id in missing:
            connection.execute(text(
                "UPDATE routing_events SET client_key = :key WHERE id = :id"
            ), {"key": str(uuid4()), "id": event_id})

    inspector = inspect(bind)
    unique_keys = inspector.get_unique_constraints("routing_events")
    indexes = inspector.get_indexes("routing_events")
    if not any(key.get("column_names") == ["client_key"] for key in unique_keys) and not any(
        index.get("unique") and index.get("column_names") == ["client_key"] for index in indexes
    ):
        with bind.begin() as connection:
            connection.execute(text(
                "CREATE UNIQUE INDEX uq_routing_events_client_key ON routing_events (client_key)"
            ))

    # MySQL supports tightening nullability in place. SQLite keeps the added
    # column nullable to avoid rebuilding the table and its foreign keys.
    column = next(column for column in inspect(bind).get_columns("routing_events") if column["name"] == "client_key")
    if bind.dialect.name == "mysql" and column["nullable"]:
        with bind.begin() as connection:
            connection.execute(text("ALTER TABLE routing_events MODIFY COLUMN client_key VARCHAR(64) NOT NULL"))
