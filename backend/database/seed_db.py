"""Initialize or upgrade the deterministic global multi-layer scenario safely.

Run from the repository root after building the inventory:
    python -m backend.database.build_global_multilayer_inventory
    python -m backend.database.seed_db
"""

import csv
from pathlib import Path

from sqlalchemy import inspect, text

from backend.database.database import engine as default_engine


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "data" / "input" / "global_ground_nodes" / "global_multilayer_nodes_106.csv"
SCENARIO_NAME = "SAGSIN-Global-Multilayer-106"


def migrate_node_metadata(bind=None):
    """Add metadata columns to an existing nodes table without dropping data."""
    engine = bind if bind is not None else default_engine
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("nodes")}
    additions = {
        "scenario_id": "INTEGER NULL",
        "country_code": "VARCHAR(3) NULL",
        "country_name": "VARCHAR(100) NULL",
        "continent": "VARCHAR(20) NULL",
        "land_area_km2": "FLOAT NULL",
        "location_name": "VARCHAR(120) NULL",
        "coordinate_source": "VARCHAR(80) NULL",
        "is_simulated": "BOOLEAN NOT NULL DEFAULT FALSE",
        "platform": "VARCHAR(30) NULL",
        "orbit_inclination_deg": "FLOAT NULL",
        "orbit_plane": "INTEGER NULL",
        "orbit_phase_deg": "FLOAT NULL",
        "orbit_raan_deg": "FLOAT NULL",
        "epoch_utc": "VARCHAR(32) NULL",
    }
    with engine.begin() as connection:
        for name, ddl in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE nodes ADD COLUMN {name} {ddl}"))

    if engine.dialect.name == "mysql":
        foreign_keys = inspect(engine).get_foreign_keys("nodes")
        if not any(
            "scenario_id" in fk.get("constrained_columns", [])
            and fk.get("referred_table") == "scenarios"
            for fk in foreign_keys
        ):
            with engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE nodes ADD CONSTRAINT fk_nodes_scenario_id "
                    "FOREIGN KEY (scenario_id) REFERENCES scenarios (id)"
                ))

    for index_name, column_name in (
        ("ix_nodes_scenario_id", "scenario_id"),
        ("ix_nodes_country_code", "country_code"),
    ):
        existing = {index["name"] for index in inspect(engine).get_indexes("nodes")}
        if index_name not in existing:
            with engine.begin() as connection:
                connection.execute(text(
                    f"CREATE INDEX {index_name} ON nodes ({column_name})"
                ))


def load_inventory():
    if not INVENTORY.exists():
        raise FileNotFoundError(
            f"Missing {INVENTORY}; run backend.database.build_global_multilayer_inventory first"
        )
    with INVENTORY.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 106:
        raise ValueError(f"Inventory must contain exactly 106 nodes, found {len(rows)}")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Inventory contains duplicate node ids")
    expected = {"GROUND": 50, "SEA": 20, "AIR": 12, "SPACE": 24}
    actual = {}
    for row in rows:
        actual[row["type"]] = actual.get(row["type"], 0) + 1
    if actual != expected:
        raise ValueError(f"Inventory layer counts must be {expected}, found {actual}")
    return rows


def seed_db():
    """Compatibility entry point: additive upgrades, never reset existing data."""
    from backend.database.init_db import init_db
    init_db()


if __name__ == "__main__":
    seed_db()
