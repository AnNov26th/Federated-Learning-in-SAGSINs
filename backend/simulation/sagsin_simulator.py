import random
import math

class SAGSINSimulator:
    def __init__(self, db_session):
        self.db = db_session
        self.nodes = []
        self.participants = []

    def generate_topology(self, num_nodes=20):
        # Generate random nodes for Space, Air, Ground, Sea
        types = ['SPACE', 'AIR', 'GROUND', 'SEA']
        self.nodes = []
        for i in range(num_nodes):
            t = random.choice(types)
            node = {
                "id": f"{t[:3]}-{i}",
                "type": t,
                "lat": random.uniform(-90, 90),
                "lng": random.uniform(-180, 180),
                "alt": 500 if t == 'SPACE' else 10 if t == 'AIR' else 0,
                "bandwidth": random.uniform(10, 100),
                "latency": random.uniform(5, 50),
                "energy": random.uniform(50, 100)
            }
            self.nodes.append(node)
        return self.nodes

    def select_participants(self, fraction=0.5):
        # Select a fraction of nodes to be participants
        k = max(1, int(len(self.nodes) * fraction))
        selected = random.sample(self.nodes, k)
        self.participants = []
        for node in selected:
            p = {
                "node_id": node["id"],
                "dataset_size": random.randint(100, 1000),
                "local_epochs": random.randint(1, 5),
                "selected": True
            }
            self.participants.append(p)
        return self.participants

    def calculate_metrics(self):
        # Compute average latency, total bandwidth, energy used
        if not self.participants:
            return {"latency": 0, "bandwidth": 0, "energy": 0}
            
        total_lat = sum(n["latency"] for n in self.nodes if any(p["node_id"] == n["id"] for p in self.participants))
        total_bw = sum(n["bandwidth"] for n in self.nodes if any(p["node_id"] == n["id"] for p in self.participants))
        energy = sum((100 - n["energy"]) for n in self.nodes)
        
        return {
            "avg_latency": total_lat / len(self.participants),
            "total_bandwidth": total_bw,
            "total_energy_consumed": energy
        }
