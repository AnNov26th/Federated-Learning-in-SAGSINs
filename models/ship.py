from .node import Node

class Ship(Node):
    """Lớp con Tàu biển (Tầng biển - Sea Layer)"""
    def __init__(
        self,
        node_id: str,
        name: str,
        lat: float,
        lon: float,
        battery: float = 100.0,
        bandwidth: float = 10.0,
        vessel_speed: float = 20.0,
        sea_state_tolerance: int = 5
    ):
        super().__init__(node_id, name, lat, lon, battery, bandwidth)
        self.layer = "Sea"
        self.vessel_speed = vessel_speed                # Tốc độ di chuyển (knots/hải lý)
        self.sea_state_tolerance = sea_state_tolerance  # Khả năng chịu cấp sóng biển (Cấp 1 - 12)

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "layer": self.layer,
            "vessel_speed": self.vessel_speed,
            "sea_state_tolerance": self.sea_state_tolerance
        })
        return data