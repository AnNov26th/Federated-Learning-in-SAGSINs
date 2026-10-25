"""Versioned event assumptions, not radio specifications or measured coverage."""
from copy import deepcopy
import math

DEVICES = {
    "smartphone": {"name": "Điện thoại 4G/5G", "access_km": {"GROUND": 5, "AIR": 5, "SEA": 2},
                   "uplink_mbps": 10, "downlink_mbps": 50, "processing_ms": 2},
    "emergency_radio": {"name": "Thiết bị dữ liệu cứu hộ", "access_km": {"GROUND": 10, "AIR": 10, "SEA": 10},
                        "uplink_mbps": 2, "downlink_mbps": 2, "processing_ms": 3},
    "satellite_terminal": {"name": "Đầu cuối vệ tinh chuyên dụng", "access_km": {"SPACE": 5000},
                           "uplink_mbps": 10, "downlink_mbps": 20, "processing_ms": 5,
                           "min_elevation_deg": 10},
    "iot_sensor": {"name": "Cảm biến IoT", "access_km": {"GROUND": 2, "AIR": 2, "SEA": 2},
                   "uplink_mbps": .1, "downlink_mbps": .1, "processing_ms": 5},
}
TRAFFIC = {
    "Message": {"kind": "burst", "direction": "uplink", "destination": "Máy chủ tin nhắn tại biên", "processing_ms": 2},
    "Video Call": {"kind": "continuous", "direction": "bidirectional", "destination": "Máy chủ chuyển tiếp cuộc gọi tại biên", "processing_ms": 3},
    "Watch Video": {"kind": "continuous", "direction": "downlink", "destination": "Bộ nhớ đệm video tại biên", "processing_ms": 2},
    "Gaming": {"kind": "interactive", "direction": "bidirectional", "destination": "Máy chủ game tại biên", "processing_ms": 2},
    "Emergency": {"kind": "alert", "direction": "uplink", "destination": "Dịch vụ tiếp nhận cứu hộ tại biên", "processing_ms": 2},
}


def resolve_event(request):
    traffic = deepcopy(TRAFFIC[request.service])
    if request.source_device == "network_gateway":
        return {"version": "virtual_gateway_v1", "selection": "explicit", "device": None,
                "traffic": traffic,
                "assumptions": ["Điểm sự kiện dùng truy cập trừu tượng có giới hạn khoảng cách theo lớp node và kiểm tra tầm nhìn; không mô phỏng radio thiết bị cá nhân.",
                                "Backbone vẫn chọn tuyến theo topology, dung lượng còn lại và checkpoint FL khi được chọn."],
                "note": "Chọn node gần nhất có đường khả thi tới đích; không nối vô hạn tới node ở xa."}
    # Explicit compatibility mode only for replaying pre-device experiments.
    if request.source_device == "legacy_simulator":
        return {"version": "legacy_v0", "device": None, "traffic": traffic,
                "note": "Kênh tổng hợp cũ để tái lập nghiên cứu; không mô phỏng khả năng thiết bị."}
    key = request.source_device
    if key == "auto":
        key = "emergency_radio" if request.service == "Emergency" else "smartphone"
    device = {"id": key, **deepcopy(DEVICES[key])}
    direction = traffic["direction"]
    device["effective_bandwidth_mbps"] = device["downlink_mbps"] if direction == "downlink" else (
        min(device["uplink_mbps"], device["downlink_mbps"]) if direction == "bidirectional" else device["uplink_mbps"])
    return {"version": "device_v1", "selection": "automatic" if request.source_device == "auto" else "explicit",
            "device": device, "traffic": traffic,
            "assumptions": ["Tầm truy cập và tốc độ thiết bị là giả định demo, không phải thông số chuẩn 4G/5G.",
                "GROUND/AIR/SEA được giả định có trạm truy cập tương thích khi profile cho phép; chưa có inventory radio từng node.",
                "Các GROUND được giả định có dịch vụ biên tương ứng. Chưa mô phỏng Internet/core, hàng đợi gói hay tranh chấp vô tuyến.",
                "Băng thông một luồng được giữ tới khi xóa hoặc tính lại sự kiện; chưa tự hết hạn phiên."]}


def device_access_limit(event, layer):
    device = event["device"]
    return None if device is None else device["access_km"].get(layer, 0)


def elevation_deg(origin, node):
    lat1, lat2 = math.radians(origin.lat), math.radians(node.lat)
    cosine = math.sin(lat1)*math.sin(lat2)+math.cos(lat1)*math.cos(lat2)*math.cos(math.radians(node.lng-origin.lng))
    angle = math.acos(max(-1., min(1., cosine)))
    radius = 6371 + max(0., node.alt)
    return math.degrees(math.atan2(radius*math.cos(angle)-6371, radius*math.sin(angle)))
