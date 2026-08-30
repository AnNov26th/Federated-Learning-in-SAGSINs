from .node import Node

class Vehicle(Node):
    """Lớp con Vehicle (Tầng Mặt đất - Ground Layer)"""
    def __init__(
        self,
        node_id: str,
        name: str,
        lat: float,
        lon: float,
        battery: float = 100.0,
        bandwidth: float = 100.0,
        speed: float = 60.0
    ):
        super().__init__(node_id, name, lat, lon, battery, bandwidth)
        self.layer = "Ground"
        self.speed = speed  # Vận tốc di chuyển trên đường (km/h)

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "layer": self.layer,
            "speed": self.speed
        })
        return data