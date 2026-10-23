"""Versioned, additive data upgrades; runs before the API accepts requests."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON, String, func, select, text
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.database.global_coverage import analytical_coverage, load_satellites
from backend.models.network import Node
from backend.models.scenario import Scenario

VERSION = "20261023_01_global_polar_coverage"
TOPOLOGY_VERSION = "20261023_02_feasible_snapshot_links"
SCENARIO_NAME = "SAGSIN-Global-Multilayer-106"


class DatabaseMigration(Base):
    __tablename__ = "database_migrations"
    version = Column(String(100), primary_key=True)
    checksum = Column(String(64), nullable=False)
    applied_at = Column(DateTime, nullable=False)
    details = Column(JSON, nullable=False)


def inventory_node(row, scenario_id):
    return Node(
        id=row['id'], type=row['type'], lat=float(row['lat']), lng=float(row['lng']),
        alt=float(row['alt_km']), bandwidth=float(row['bandwidth_mbps']), latency=float(row['latency_ms']),
        battery_percent=float(row['battery_percent']), status=row['status'], scenario_id=scenario_id,
        country_code=row['country_code'] or None, country_name=row['country_name'] or None,
        continent=row['continent'] or None, land_area_km2=float(row['land_area_km2']) if row['land_area_km2'] else None,
        location_name=row['location_name'] or None, coordinate_source=row['coordinate_source'] or None,
        is_simulated=row['is_simulated'].lower() == 'true', platform=row['platform'] or None,
        orbit_inclination_deg=float(row['orbit_inclination_deg']) if row['orbit_inclination_deg'] else None,
        orbit_plane=int(row['orbit_plane']) if row['orbit_plane'] else None,
        orbit_phase_deg=float(row['orbit_phase_deg']) if row['orbit_phase_deg'] else None,
        orbit_raan_deg=float(row['orbit_raan_deg']) if row.get('orbit_raan_deg') else None,
        epoch_utc=row['epoch_utc'] or None,
    )


def add_global_coverage(db, satellite_rows):
    matches = db.scalars(select(Scenario).where(Scenario.name == SCENARIO_NAME)).all()
    if len(matches) > 1:
        raise RuntimeError(f"Multiple scenarios named {SCENARIO_NAME}; resolve duplicates before upgrading.")
    scenario = matches[0] if matches else None
    baseline_added = 0
    if scenario is None:
        # Bootstrap a fresh checkout without calling the destructive legacy seeder.
        from backend.database.seed_db import load_inventory
        baseline = load_inventory()
        ids = [row['id'] for row in baseline]
        collisions = db.scalars(select(Node.id).where(Node.id.in_(ids))).all()
        if collisions:
            raise RuntimeError(f"Base inventory ID collision: {collisions[:5]}; no existing records were overwritten.")
        scenario = Scenario(name=SCENARIO_NAME)
        db.add(scenario); db.flush()
        db.add_all([inventory_node(row, scenario.id) for row in baseline])
        baseline_added = len(baseline)
        db.flush()
    added = []
    for row in satellite_rows:
        existing = db.get(Node, row['id'])
        if existing is not None:
            if (existing.scenario_id != scenario.id or existing.type != "SPACE"
                    or existing.coordinate_source != row['coordinate_source']):
                raise RuntimeError(f"Satellite ID collision: {row['id']}; no existing records were overwritten.")
            continue
        db.add(inventory_node(row, scenario.id)); added.append(row['id'])
    db.flush()
    counts = dict(db.execute(select(Node.type, func.count()).where(Node.scenario_id == scenario.id).group_by(Node.type)).all())
    scenario.total_nodes = sum(counts.values())
    for layer, field in [('SPACE', 'space'), ('AIR', 'air'), ('SEA', 'sea'), ('GROUND', 'ground')]:
        setattr(scenario, field, counts.get(layer, 0))
    return {"scenario_id": scenario.id, "baseline_nodes_added": baseline_added,
            "satellites_added": added, "layer_counts": counts, "coverage": analytical_coverage()}


def apply_data_migrations(bind):
    rows = load_satellites()
    from backend.services.topology_service import connect_feasible_snapshot
    topology_checksum = inventory_checksum({'version': TOPOLOGY_VERSION, 'neighbors': 4,
        'space_km': 5000, 'air_km': 1500, 'surface_km': 500,
        'los': True, 'preserve_inactive': True, 'ground_backbone': 'existing_only'})
    # MySQL named lock serializes multiple uvicorn workers sharing the database.
    lock = "sagsin_upgrade_" + hashlib.sha256(str(bind.url.database).encode()).hexdigest()[:16]
    with bind.connect() as connection:
        mysql = bind.dialect.name == 'mysql'
        if mysql:
            acquired = connection.scalar(text("SELECT GET_LOCK(:name, 60)"), {"name": lock})
            connection.commit()
            if acquired != 1:
                raise RuntimeError("Timed out waiting for database migration lock.")
        try:
            with Session(bind=connection) as db, db.begin():
                applied = []
                original_details = None
                for version, checksum in [(VERSION, inventory_checksum(rows)), (TOPOLOGY_VERSION, topology_checksum)]:
                    previous = db.get(DatabaseMigration, version)
                    if previous:
                        if previous.checksum != checksum:
                            raise RuntimeError("An applied migration inventory changed; publish a new migration version.")
                        details = previous.details
                        already_applied = True
                    else:
                        if version == VERSION:
                            details = add_global_coverage(db, rows)
                        elif db.get(Scenario, original_details['scenario_id']) is not None:
                            details = connect_feasible_snapshot(db, original_details['scenario_id'], neighbors=4)
                        else:
                            details = {'skipped': 'Original scenario was deleted; no user data recreated.'}
                        db.add(DatabaseMigration(version=version, checksum=checksum,
                            applied_at=datetime.now(timezone.utc), details=details))
                        already_applied = False
                    if version == VERSION:
                        original_details = details
                    applied.append({'version': version, 'already_applied': already_applied, 'details': details})
            for item in applied:
                if not item['already_applied']:
                    print(f"Applied {item['version']}.")
            return {"version": VERSION, "already_applied": all(item['already_applied'] for item in applied),
                    "details": original_details, "migrations": applied}
        finally:
            if mysql:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock})
                connection.commit()


def inventory_checksum(rows):
    """Hash parsed values so Git LF/CRLF conversion does not change a version."""
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
