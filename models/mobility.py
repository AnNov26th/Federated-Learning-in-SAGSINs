import math
import random


class MobilityEngine:
    @staticmethod
    def update_positions(nodes_list, step_time=1.0):
        """
        Cập nhật tọa độ di chuyển thực tế cho từng loại thiết bị biên SAGSINs
        """
        for node in nodes_list:
            layer = getattr(node, 'layer', 'Ground')

            if layer == "Space":  # Vệ tinh LEO di chuyển theo quỹ đạo nhanh
                node.lon += 0.35 * step_time
                if node.lon > 180:
                    node.lon -= 360
                node.lat += 0.12 * math.sin(node.lon * math.pi / 180.0)

            elif layer == "Air":  # UAV bay tuần tra bán kính
                angle = random.uniform(0, 2 * math.pi)
                radius = 0.015 * step_time
                node.lat += radius * math.cos(angle)
                node.lon += radius * math.sin(angle)

            elif layer == "Sea":  # Tàu biển di chuyển ven bờ/hải đảo
                node.lat += random.uniform(-0.008, 0.008) * step_time
                node.lon += random.uniform(-0.008, 0.008) * step_time

            elif layer == "Ground":  # Xe thông minh di chuyển trên đường
                node.lat += random.uniform(-0.004, 0.004) * step_time
                node.lon += random.uniform(-0.004, 0.004) * step_time

            # Đảm bảo giữ trong phạm vi tọa độ hợp lệ
            node.lat = max(-85.0, min(85.0, node.lat))
            node.lon = max(-180.0, min(180.0, node.lon))