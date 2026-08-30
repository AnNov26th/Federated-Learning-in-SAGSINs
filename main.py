from models import GroundStation, UAV, Satellite, Ship, Vehicle
from models.fl_core import SimpleCNN, federated_averaging

def run_simulation_demo():
    print("==================================================")
    print("🚀 KHỞI CHẠY MÔ PHỎNG FEDERATED LEARNING IN SAGSINs")
    print("==================================================\n")

    # 1. Khởi tạo Trạm mặt đất (Server)
    gs = GroundStation(station_id="GS_DANANG", name="Trạm Mặt Đất Đà Nẵng")
    print(f"🏠 Khởi tạo {gs.name} làm Central Server.")

    # 2. Khởi tạo các Nút biên ở 4 tầng mạng (Clients)
    clients = [
        Satellite("SAT_01", "Vệ tinh LEO", 16.8000, 107.8000),
        UAV("UAV_01", "Drone Giám sát", 16.2000, 108.3000),
        Ship("SHIP_01", "Tàu biển Hải quân", 15.8000, 108.8000),
        Vehicle("VEH_01", "Xe tự hành IoV", 16.0200, 108.1800)
    ]

    # Đăng ký các nút với Trạm mặt đất
    for client in clients:
        gs.register_client(client)
        print(f"  └─ 🤝 Đăng ký nút: {client.name} (Tầng: {client.layer})")

    # 3. Giả lập 1 vòng huấn luyện và tổng hợp FedAvg
    print("\n🔄 [Round 1] Bắt đầu quá trình Học liên hợp...")
    global_model = SimpleCNN()
    collected_weights = []

    for client in clients:
        client.update_status("TRAINING")
        print(f"  ⚡ [{client.node_id}] Đang huấn luyện mô hình cục bộ...")
        # Lấy trọng số mô hình cục bộ (giả lập)
        local_weight = global_model.state_dict()
        collected_weights.append(local_weight)
        client.update_status("IDLE")

    # 4. Trạm mặt đất thực hiện tổng hợp FedAvg
    print("\n📡 Trạm mặt đất đang tính toán tổng hợp trọng số FedAvg...")
    updated_global_weights = federated_averaging(collected_weights)
    gs.aggregation_round += 1

    print(f"✅ Hoàn thành Vòng {gs.aggregation_round}! Mô hình toàn cục đã được cập nhật thành công.")
    print("==================================================")

if __name__ == "__main__":
    run_simulation_demo()