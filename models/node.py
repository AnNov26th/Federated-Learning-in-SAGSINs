import numpy as np

class Node:
    """Lớp cha cơ sở đại diện cho một nút mạng trong SAGSINs"""
    def __init__(
        self,
        node_id: str,
        name: str,
        lat: float,
        lon: float,
        battery: float = 100.0,
        bandwidth: float = 50.0,
        status: str = "IDLE"
    ):
        self.node_id = node_id
        self.name = name
        self.lat = lat                  # Tọa độ Vĩ độ
        self.lon = lon                  # Tọa độ Kinh độ
        self.battery = battery          # Mức pin (%) [0.0 -> 100.0]
        self.bandwidth = bandwidth      # Băng thông (Mbps)
        self.status = status            # Trạng thái: IDLE, TRAINING, TRANSMITTING, OFFLINE

    def update_location(self, new_lat: float, new_lon: float):
        """Cập nhật tọa độ di chuyển của nút"""
        self.lat = new_lat
        self.lon = new_lon

    def update_status(self, new_status: str):
        """Cập nhật trạng thái hoạt động"""
        self.status = new_status

    def consume_battery(self, amount: float):
        """Mô phỏng tiêu thụ năng lượng pin"""
        self.battery = max(0.0, self.battery - amount)
        if self.battery == 0.0:
            self.status = "OFFLINE"

    def to_dict(self) -> dict:
        """Xuất thông tin nút dạng Dictionary cho API / Dashboard"""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "battery": self.battery,
            "bandwidth": self.bandwidth,
            "status": self.status
        }