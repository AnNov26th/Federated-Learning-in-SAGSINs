import random
import math
from backend.database.database import SessionLocal
from backend.models.network import Node
from backend.models.participant import Participant
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLRound, Metric

def seed_fl():
    print("Seeding FL simulation data (Participants, Rounds, Metrics)...")
    db = SessionLocal()
    try:
        # Get scenario
        scenario = db.query(Scenario).first()
        if not scenario:
            print("No scenario found. Run seed_db.py first.")
            return

        # 1. Clear old FL data
        db.query(Metric).delete()
        db.query(FLRound).delete()
        db.query(Experiment).delete()
        db.query(Participant).delete()
        db.commit()

        # 2. Select Participants
        nodes = db.query(Node).all()
        if not nodes:
            print("No nodes found.")
            return
            
        selected_nodes = random.sample(nodes, min(15, len(nodes)))
        participants = []
        for n in selected_nodes:
            p = Participant(
                node_id=n.id,
                dataset_size=random.randint(500, 2000),
                local_epochs=random.randint(1, 5),
                selected=True
            )
            participants.append(p)
        db.add_all(participants)
        db.flush()

        # 3. Create Experiment
        exp = Experiment(
            scenario_id=scenario.id,
            algorithm="FedAvg",
            rounds=20,
            learning_rate=0.01
        )
        db.add(exp)
        db.flush()

        # 4. Simulate Rounds & Metrics
        current_acc = 10.0
        current_loss = 2.5
        
        rounds_data = []
        metrics_data = []
        
        for r in range(1, 21):
            # Simulate FedAvg progress
            acc_gain = random.uniform(2.0, 5.0) * (math.exp(-r/10))
            loss_drop = random.uniform(0.05, 0.2) * (math.exp(-r/10))
            
            current_acc = min(98.5, current_acc + acc_gain)
            current_loss = max(0.1, current_loss - loss_drop)
            
            round_obj = FLRound(
                experiment_id=exp.id,
                round=r,
                participants_count=len(selected_nodes),
                accuracy=current_acc,
                loss=current_loss,
                time=random.uniform(5.0, 15.0)
            )
            db.add(round_obj)
            db.flush()
            
            # Metrics
            m = Metric(
                round_id=round_obj.id,
                latency=random.uniform(20.0, 100.0),
                communication_time=random.uniform(2.0, 8.0),
                energy_consumption=random.uniform(10.0, 30.0),
                bandwidth_usage=random.uniform(50.0, 200.0),
                data_transferred=random.uniform(10.0, 50.0),
                packet_loss=random.uniform(0.0, 2.0)
            )
            metrics_data.append(m)
            
        db.add_all(metrics_data)
        db.commit()
        print("FL Data seeded successfully! Added Experiment, 20 Rounds and Metrics.")
        
    except Exception as e:
        print(f"Error seeding FL data: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_fl()
