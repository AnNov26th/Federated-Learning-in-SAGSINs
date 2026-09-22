import random
from backend.database.database import SessionLocal, engine, Base
from backend.models.scenario import Scenario
from backend.models.network import Node, NetworkLink

def seed_db():
    print("Seeding database with SAGSIN-50 scenario...")
    
    # 0. Drop and recreate tables to ensure clean slate
    print("Resetting tables...")
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        Base.metadata.drop_all(bind=engine)
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # 1. Create Scenario
        scenario = Scenario(
            name="SAGSIN-50",
            total_nodes=50,
            space=10,
            air=12,
            ground=23,
            sea=5
        )
        db.add(scenario)
        
        nodes = []
        
        # Helper function to generate random lat/lng
        def r_lat(): return random.uniform(-60, 60)
        def r_lng(): return random.uniform(-180, 180)
        
        # 2. SPACE (10 nodes)
        # GEO (2)
        for i in range(1, 3):
            nodes.append(Node(id=f"GEO-{i:02d}", type="SPACE", lat=r_lat(), lng=r_lng(), alt=35786, bandwidth=100.0, latency=250.0, energy=100.0))
        # MEO (3)
        for i in range(1, 4):
            nodes.append(Node(id=f"MEO-{i:02d}", type="SPACE", lat=r_lat(), lng=r_lng(), alt=10000, bandwidth=150.0, latency=100.0, energy=90.0))
        # LEO (5)
        for i in range(1, 6):
            nodes.append(Node(id=f"LEO-{i:02d}", type="SPACE", lat=r_lat(), lng=r_lng(), alt=600, bandwidth=50.0, latency=30.0, energy=85.0))
            
        # 3. AIR (12 nodes)
        # HAP (2)
        for i in range(1, 3):
            nodes.append(Node(id=f"HAP-{i:02d}", type="AIR", lat=r_lat(), lng=r_lng(), alt=20, bandwidth=30.0, latency=15.0, energy=70.0))
        # Aircraft (3)
        for i in range(1, 4):
            nodes.append(Node(id=f"AIR-{i:02d}", type="AIR", lat=r_lat(), lng=r_lng(), alt=10, bandwidth=20.0, latency=10.0, energy=80.0))
        # UAV (5)
        for i in range(1, 6):
            nodes.append(Node(id=f"UAV-{i:02d}", type="AIR", lat=r_lat(), lng=r_lng(), alt=1, bandwidth=10.0, latency=5.0, energy=50.0))
        # eVTOL (2)
        for i in range(1, 3):
            nodes.append(Node(id=f"EVT-{i:02d}", type="AIR", lat=r_lat(), lng=r_lng(), alt=0.5, bandwidth=15.0, latency=2.0, energy=60.0))
            
        # 4. GROUND (23 nodes)
        # Base Station (5)
        for i in range(1, 6):
            nodes.append(Node(id=f"BS-{i:02d}", type="GROUND", lat=r_lat(), lng=r_lng(), alt=0.05, bandwidth=500.0, latency=1.0, energy=100.0))
        # Edge Server (3)
        for i in range(1, 4):
            nodes.append(Node(id=f"EDGE-{i:02d}", type="GROUND", lat=r_lat(), lng=r_lng(), alt=0.0, bandwidth=1000.0, latency=0.5, energy=100.0))
        # Vehicle (8)
        for i in range(1, 9):
            nodes.append(Node(id=f"VEH-{i:02d}", type="GROUND", lat=r_lat(), lng=r_lng(), alt=0.0, bandwidth=5.0, latency=10.0, energy=40.0))
        # IoT Device (7)
        for i in range(1, 8):
            nodes.append(Node(id=f"IOT-{i:02d}", type="GROUND", lat=r_lat(), lng=r_lng(), alt=0.0, bandwidth=1.0, latency=20.0, energy=20.0))
            
        # 5. SEA (5 nodes)
        # Buoy (2)
        for i in range(1, 3):
            nodes.append(Node(id=f"BUOY-{i:02d}", type="SEA", lat=r_lat(), lng=r_lng(), alt=0.0, bandwidth=2.0, latency=50.0, energy=30.0))
        # Vessel (2)
        for i in range(1, 3):
            nodes.append(Node(id=f"VES-{i:02d}", type="SEA", lat=r_lat(), lng=r_lng(), alt=0.0, bandwidth=10.0, latency=35.0, energy=80.0))
        # Shallow-water (1)
        for i in range(1, 2):
            nodes.append(Node(id=f"SHA-{i:02d}", type="SEA", lat=r_lat(), lng=r_lng(), alt=-0.1, bandwidth=1.0, latency=80.0, energy=25.0))

        db.add_all(nodes)
        db.flush() # Commit nodes to DB to resolve foreign key constraints
        
        # 6. Create some random Network Links (just a few for visual testing)
        links = []
        for i in range(20): # create 20 random links
            source = random.choice(nodes)
            target = random.choice(nodes)
            if source.id != target.id:
                links.append(NetworkLink(source=source.id, target=target.id, distance=random.uniform(10, 1000), bandwidth=random.uniform(5, 50), latency=random.uniform(1, 100)))
        db.add_all(links)
        
        db.commit()
        print(f"Database seeded successfully with {len(nodes)} nodes in scenario SAGSIN-50!")
    except Exception as e:
        print(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
