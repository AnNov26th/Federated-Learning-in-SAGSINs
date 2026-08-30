class GroundStation:
    """Lớp Trạm Mặt Đất (Central Aggregator / Server)"""
    def __init__(self, station_id: str = "GS_DANANG", name: str = "Trạm Mặt Đất Đà Nẵng", lat: float = 16.0544, lon: float = 108.2022):
        self.station_id = station_id
        self.name = name
        self.lat = lat
        self.lon = lon
        self.connected_clients = {}  # Lưu danh sách nút kết nối {node_id: Node_object}
        self.global_weights = None   # Lưu bộ trọng số toàn cục PyTorch
        self.aggregation_round = 0  # Vòng lặp tổng hợp hiện tại

    def register_client(self, client_node):
        """Đăng ký nút biên tham gia mạng"""
        self.connected_clients[client_node.node_id] = client_node

    def unregister_client(self, node_id: str):
        """Hủy đăng ký nút biên"""
        if node_id in self.connected_clients:
            del self.connected_clients[node_id]

    def to_dict(self) -> dict:
        return {
            "station_id": self.station_id,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "connected_clients_count": len(self.connected_clients),
            "aggregation_round": self.aggregation_round
        }