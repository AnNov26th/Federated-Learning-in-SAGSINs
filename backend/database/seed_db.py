"""Replace demo topology with the deterministic global multi-layer scenario.

Run from the repository root after building the inventory:
    python -m backend.database.build_global_multilayer_inventory
    python -m backend.database.seed_db
"""

import csv
from pathlib import Path

from sqlalchemy import inspect, text

from backend.database.database import Base, SessionLocal, engine
from backend.models.network import Node, NetworkLink
from backend.models.participant import Participant
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLClientRound, FLRound, Metric


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "data" / "global_ground_nodes" / "global_multilayer_nodes_106.csv"
SCENARIO_NAME = "SAGSIN-Global-Multilayer-106"


def migrate_node_metadata():
    """Add metadata columns to an existing nodes table without dropping data."""
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
    rows = load_inventory()
    Base.metadata.create_all(bind=engine)
    migrate_node_metadata()
    db = SessionLocal()
    try:
        # The user identified all previous topology and FL records as test data.
        # Delete dependent rows first so every backend supported FK remains valid.
        db.query(FLClientRound).delete(synchronize_session=False)
        db.query(Metric).delete(synchronize_session=False)
        db.query(FLRound).delete(synchronize_session=False)
        db.query(Experiment).delete(synchronize_session=False)
        db.query(Participant).delete(synchronize_session=False)
        db.query(NetworkLink).delete(synchronize_session=False)
        db.query(Node).delete(synchronize_session=False)
        db.query(Scenario).delete(synchronize_session=False)
        db.flush()

        scenario = Scenario(
            name=SCENARIO_NAME,
            total_nodes=len(rows),
            space=sum(row["type"] == "SPACE" for row in rows),
            air=sum(row["type"] == "AIR" for row in rows),
            ground=sum(row["type"] == "GROUND" for row in rows),
            sea=sum(row["type"] == "SEA" for row in rows),
        )
        db.add(scenario)
        db.flush()

        nodes = [Node(
            id=row["id"],
            type=row["type"],
            lat=float(row["lat"]),
            lng=float(row["lng"]),
            alt=float(row["alt_km"]),
            bandwidth=float(row["bandwidth_mbps"]),
            latency=float(row["latency_ms"]),
            battery_percent=float(row["battery_percent"]),
            status=row["status"],
            scenario_id=scenario.id,
            country_code=row["country_code"] or None,
            country_name=row["country_name"] or None,
            continent=row["continent"] or None,
            land_area_km2=float(row["land_area_km2"]) if row["land_area_km2"] else None,
            location_name=row["location_name"] or None,
            coordinate_source=row["coordinate_source"] or None,
            is_simulated=row["is_simulated"].lower() == "true",
            platform=row["platform"] or None,
            orbit_inclination_deg=(float(row["orbit_inclination_deg"])
                                   if row["orbit_inclination_deg"] else None),
            orbit_plane=int(row["orbit_plane"]) if row["orbit_plane"] else None,
            orbit_phase_deg=(float(row["orbit_phase_deg"])
                             if row["orbit_phase_deg"] else None),
            epoch_utc=row["epoch_utc"] or None,
        ) for row in rows]
        db.add_all(nodes)
        db.commit()
        print(
            f"Inserted {len(nodes)} nodes (GROUND=50, SEA=20, AIR=12, SPACE=24) "
            f"in {SCENARIO_NAME}."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_db()
