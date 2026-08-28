import numpy as np

class Node:
    """Lớp cha cơ sở đại diện cho một nút mạng"""
    def __init__(self, node_id: str, name: str, lat: float, lon: float, battery: float, bandwidth: float):
        self.node_id = node_id
        self.name = name
        self.lat = lat                  # Tọa độ Vĩ độ
        self.lon = lon                  # Tọa độ Kinh độ
        self.battery = battery          # Mức pin (%)
        self.bandwidth = bandwidth      # Băng thông (Mbps)
        self.status = "IDLE"            # Trạng thái: IDLE, TRAINING, TRANSMITTING, OFFLINE

    def update_location(self, new_lat: float, new_lon: float):
        self.lat = new_lat
        self.lon = new_lon

class UAV(Node):
    """Lớp con UAV (Tầng trên không)"""
    def __init__(self, node_id, name, lat, lon, battery=100.0, bandwidth=50.0):
        super().__init__(node_id, name, lat, lon, battery, bandwidth)
        self.layer = "Air"

class Satellite(Node):
    """Lớp con Vệ tinh (Tầng không gian)"""
    def __init__(self, node_id, name, lat, lon, battery=100.0, bandwidth=20.0, orbit_altitude=800):
        super().__init__(node_id, name, lat, lon, battery, bandwidth)
        self.orbit_altitude = orbit_altitude # Độ cao quỹ đạo (km)
        self.layer = "Space"

class Ship(Node):
    """Lớp con Tàu biển (Tầng biển)"""
    def __init__(self, node_id, name, lat, lon, battery=100.0, bandwidth=10.0):
        super().__init__(node_id, name, lat, lon, battery, bandwidth)
        self.layer = "Sea"