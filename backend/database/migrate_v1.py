import json
from datetime import datetime, timezone
from sqlalchemy import text
from backend.database.database import engine, Base
import backend.models.network
import backend.models.participant
import backend.models.scenario
import backend.models.simulation

def run_migration():
    print("Starting DB Migration v1...")
    
    with engine.connect() as conn:
        # Check if already migrated
        result = conn.execute(text("SHOW COLUMNS FROM experiments LIKE 'status'"))
        if result.fetchone():
            print("Migration already applied (experiments.status exists). Exiting.")
            return

        # 1. Read existing data
        print("Reading existing data...")
        try:
            nodes = [dict(row._mapping) for row in conn.execute(text("SELECT * FROM nodes"))]
            links = [dict(row._mapping) for row in conn.execute(text("SELECT * FROM network_links"))]
            experiments = [dict(row._mapping) for row in conn.execute(text("SELECT * FROM experiments"))]
            fl_rounds = [dict(row._mapping) for row in conn.execute(text("SELECT * FROM fl_rounds"))]
            metrics = [dict(row._mapping) for row in conn.execute(text("SELECT * FROM metrics"))]
            scenarios = [dict(row._mapping) for row in conn.execute(text("SELECT * FROM scenarios"))]
            participants = [dict(row._mapping) for row in conn.execute(text("SELECT * FROM participants"))]
        except Exception as e:
            print("Error reading existing data, maybe tables are already dropped?", e)
            nodes, links, experiments, fl_rounds, metrics, scenarios, participants = [], [], [], [], [], [], []

        # 2. Drop all tables
        print("Dropping old tables...")
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
        conn.execute(text("DROP TABLE IF EXISTS metrics;"))
        conn.execute(text("DROP TABLE IF EXISTS fl_rounds;"))
        conn.execute(text("DROP TABLE IF EXISTS participants;"))
        conn.execute(text("DROP TABLE IF EXISTS experiments;"))
        conn.execute(text("DROP TABLE IF EXISTS network_links;"))
        conn.execute(text("DROP TABLE IF EXISTS nodes;"))
        conn.execute(text("DROP TABLE IF EXISTS scenarios;"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
        conn.commit()

    # 3. Create new tables
    print("Creating new schema...")
    Base.metadata.create_all(bind=engine)

    # 4. Backfill data
    print("Backfilling data with new schema & standardizing units...")
    with engine.connect() as conn:
        with conn.begin():
            # Scenarios
            for s in scenarios:
                conn.execute(text("INSERT INTO scenarios (id, name, total_nodes, space, air, ground, sea) VALUES (:id, :name, :total_nodes, :space, :air, :ground, :sea)"), s)
            
            # Nodes
            for n in nodes:
                conn.execute(text("""
                    INSERT INTO nodes (id, type, lat, lng, alt, bandwidth, latency, battery_percent, status, last_heartbeat) 
                    VALUES (:id, :type, :lat, :lng, :alt, :bandwidth, :latency, :battery, 'ACTIVE', NULL)
                """), {
                    "id": n["id"], "type": n["type"], "lat": n["lat"], "lng": n["lng"], 
                    "alt": n["alt"], "bandwidth": n["bandwidth"], "latency": n["latency"],
                    "battery": n.get("energy", 100.0) # Map old 'energy' to 'battery_percent'
                })
                
            # Links
            for l in links:
                conn.execute(text("""
                    INSERT INTO network_links (id, source, target, distance, bandwidth, latency, status, last_heartbeat)
                    VALUES (:id, :source, :target, :distance, :bandwidth, :latency, :status, NULL)
                """), {
                    "id": l["id"], "source": l["source"], "target": l["target"], 
                    "distance": l["distance"], "bandwidth": l["bandwidth"], "latency": l["latency"],
                    "status": l.get("status", "ACTIVE")
                })
                
            # Participants
            for p in participants:
                conn.execute(text("""
                    INSERT INTO participants (id, node_id, dataset_size, local_epochs, selected)
                    VALUES (:id, :node_id, :dataset_size, :local_epochs, :selected)
                """), p)

            # Experiments
            for e in experiments:
                # Guess completed status
                status = "COMPLETED"
                conn.execute(text("""
                    INSERT INTO experiments (id, scenario_id, algorithm, rounds, learning_rate, status, created_at, started_at, completed_at, error_message, is_simulation, config_json)
                    VALUES (:id, :scenario_id, :algorithm, :rounds, :learning_rate, :status, :created_at, :started_at, :completed_at, NULL, 1, NULL)
                """), {
                    "id": e["id"], "scenario_id": e["scenario_id"], "algorithm": e["algorithm"],
                    "rounds": e["rounds"], "learning_rate": e["learning_rate"],
                    "status": status,
                    "created_at": datetime.now(timezone.utc),
                    "started_at": datetime.now(timezone.utc),
                    "completed_at": datetime.now(timezone.utc)
                })
                
            # FL Rounds
            for r in fl_rounds:
                # Convert accuracy (0-100 to 0.0-1.0)
                acc = r["accuracy"]
                if acc > 1.0: acc = acc / 100.0
                
                conn.execute(text("""
                    INSERT INTO fl_rounds (id, experiment_id, round, participants_count, accuracy, loss, round_duration_s)
                    VALUES (:id, :experiment_id, :round, :participants_count, :accuracy, :loss, :round_duration_s)
                """), {
                    "id": r["id"], "experiment_id": r["experiment_id"], "round": r["round"],
                    "participants_count": r["participants_count"], 
                    "accuracy": acc, 
                    "loss": r["loss"],
                    "round_duration_s": r.get("time", 10.0) # Map old 'time' to 'round_duration_s'
                })
                
            # Metrics
            for m in metrics:
                # Convert packet loss (e.g. 2% -> 0.02) if needed
                pl = m.get("packet_loss", 0.0)
                if pl > 1.0: pl = pl / 100.0
                
                conn.execute(text("""
                    INSERT INTO metrics (id, round_id, latency_ms, communication_time_ms, energy_j, bandwidth_mbps, data_transferred_mb, packet_loss_ratio)
                    VALUES (:id, :round_id, :latency_ms, :communication_time_ms, :energy_j, :bandwidth_mbps, :data_transferred_mb, :packet_loss_ratio)
                """), {
                    "id": m["id"], "round_id": m["round_id"], 
                    "latency_ms": m.get("latency", 50.0), 
                    "communication_time_ms": m.get("communication_time", 5.0) * 1000, # Convert seconds to ms (assuming old was seconds)
                    "energy_j": m.get("energy_consumption", 20.0), 
                    "bandwidth_mbps": m.get("bandwidth_usage", 100.0), 
                    "data_transferred_mb": m.get("data_transferred", 10.0), 
                    "packet_loss_ratio": pl
                })
                
    print("Migration completed successfully!")

if __name__ == "__main__":
    run_migration()
