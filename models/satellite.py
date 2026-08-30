from .node import Node

class Satellite(Node):
    """Lớp con Vệ tinh (Tầng không gian - Space Layer)"""
    def __init__(
        self,
        node_id: str,
        name: str,
        lat: float,
        lon: float,
        battery: float = 100.0,
        bandwidth: float = 20.0,
        orbit_altitude: float = 800.0,
        orbit_period: float = 90.0,
        visibility_window: float = 600.0
    ):
        super().__init__(node_id, name, lat, lon, battery, bandwidth)
        self.layer = "Space"
        self.orbit_altitude = orbit_altitude      # Độ cao quỹ đạo (km) - Quỹ đạo LEO
        self.orbit_period = orbit_period          # Chu kỳ quay (phút)
        self.visibility_window = visibility_window# Cửa sổ thời gian kết nối (giây)

    def calculate_position(self, time_step: float):
        """Mô phỏng thay đổi tọa độ kinh độ theo quỹ đạo thời gian quay"""
        self.lon = (self.lon + (360.0 / (self.orbit_period * 60)) * time_step) % 360.0 - 180.0

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "layer": self.layer,
            "orbit_altitude": self.orbit_altitude,
            "orbit_period": self.orbit_period,
            "visibility_window": self.visibility_window
        })
        return data