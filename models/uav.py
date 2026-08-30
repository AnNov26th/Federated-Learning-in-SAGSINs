from .node import Node

class UAV(Node):
    """Lớp con UAV (Tầng trên không - Air Layer)"""
    def __init__(
        self,
        node_id: str,
        name: str,
        lat: float,
        lon: float,
        battery: float = 100.0,
        bandwidth: float = 50.0,
        flight_speed: float = 15.0,
        max_altitude: float = 150.0,
        energy_consumption_rate: float = 0.5
    ):
        super().__init__(node_id, name, lat, lon, battery, bandwidth)
        self.layer = "Air"
        self.flight_speed = flight_speed                      # Vận tốc bay (m/s)
        self.max_altitude = max_altitude                      # Độ cao bay tối đa (m)
        self.energy_consumption_rate = energy_consumption_rate # Tốc độ tiêu thụ pin (%/phút)

    def adjust_trajectory(self, target_lat: float, target_lon: float):
        """Mô phỏng điều chỉnh quỹ đạo bay về vị trí mục tiêu"""
        self.update_location(target_lat, target_lon)
        self.consume_battery(self.energy_consumption_rate * 0.1)

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "layer": self.layer,
            "flight_speed": self.flight_speed,
            "max_altitude": self.max_altitude,
            "energy_consumption_rate": self.energy_consumption_rate
        })
        return data