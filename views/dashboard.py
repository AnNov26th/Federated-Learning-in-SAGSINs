import sys
import os

# BẮT BỘC: Bổ sung thư mục gốc dự án vào Python Path để Streamlit Cloud nhận diện gói models
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd

# Import các đối tượng từ gói models
from models import GroundStation, UAV, Satellite, Ship, Vehicle

# 1. Cấu hình trang Dashboard
st.set_page_config(
    page_title="PBL4 - SAGSINs Federated Learning Dashboard",
    page_icon="📡",
    layout="wide"
)

st.title("📡 MÔ PHỎNG FEDERATED LEARNING TRONG MẠNG TÍCH HỢP SAGSINs")
st.subheader("Đồ án Dự án Hệ điều hành & Mạng máy tính (PBL4)")

# 2. Khởi tạo các thực thể mạng SAGSINs
gs = GroundStation(station_id="GS_DANANG", name="Trạm Mặt Đất Đà Nẵng", lat=16.0544, lon=108.2022)
uav = UAV(node_id="UAV_01", name="Drone Giám Sát", lat=16.2000, lon=108.3000, battery=95.0, bandwidth=50.0)
sat = Satellite(node_id="SAT_01", name="Vệ Tinh LEO", lat=16.8000, lon=107.8000, battery=100.0, bandwidth=20.0,
                orbit_altitude=800)
ship = Ship(node_id="SHIP_01", name="Tàu Biển Hải Quân", lat=15.8000, lon=108.8000, battery=88.0, bandwidth=10.0)
vehicle = Vehicle(node_id="VEH_01", name="Xe Tự Hành Thông Minh", lat=16.0200, lon=108.1800, battery=90.0,
                  bandwidth=100.0)

# 3. Sidebar cấu hình kịch bản
st.sidebar.header("⚙️ Cấu hình Kịch bản SAGSINs")
num_rounds = st.sidebar.slider("Số vòng huấn luyện (Rounds)", 5, 50, 10)

nodes_dict = {
    f"🛸 {uav.name} (Air Layer)": uav,
    f"🛰️ {sat.name} (Space Layer)": sat,
    f"🚢 {ship.name} (Sea Layer)": ship,
    f"🚗 {vehicle.name} (Ground Layer)": vehicle
}

selected_node_names = st.sidebar.multiselect(
    "Chọn nút biên tham gia học liên hợp:",
    list(nodes_dict.keys()),
    default=list(nodes_dict.keys())
)

# =========================================================
# PHẦN 1: BẢN ĐỒ MẠNG TÍCH HỢP SAGSINs (Ở GIỮA MÀN HÌNH CHÍNH)
# =========================================================
st.markdown("### 🗺️ Bản đồ Mạng Tích hợp SAGSINs (Google Maps GIS)")

# Khởi tạo bản đồ trung tâm tại Trạm mặt đất Đà Nẵng
m = folium.Map(
    location=[gs.lat, gs.lon],
    zoom_start=7,
    tiles=None
)

# Thêm Lớp Google Maps Vệ tinh + Địa danh (Google Hybrid)
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attr="Google Maps",
    name="Google Maps (Vệ tinh + Địa danh)",
    overlay=False,
    control=True
).add_to(m)

# Thêm Lớp Google Maps Vệ tinh thuần
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Maps",
    name="Google Maps (Ảnh Vệ tinh)",
    overlay=False,
    control=True
).add_to(m)

# Thêm Lớp Google Maps Đường xá
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
    attr="Google Maps",
    name="Google Maps (Đường xá)",
    overlay=False,
    control=True
).add_to(m)

# Thêm Lớp Giao diện Tối Dark Mode
folium.TileLayer(
    tiles="CartoDB dark_matter",
    attr="CartoDB",
    name="Giao diện Tối (Dark Mode)",
    overlay=False,
    control=True
).add_to(m)

# Marker Trạm Mặt Đất (Server Trung tâm)
folium.Marker(
    [gs.lat, gs.lon],
    popup=f"<b>{gs.name} ({gs.station_id})</b><br>Vai trò: Central Aggregator<br>Tọa độ: {gs.lat}, {gs.lon}",
    icon=folium.Icon(color="red", icon="home")
).add_to(m)

color_map = {"Air": "green", "Space": "blue", "Sea": "orange", "Ground": "purple"}
icon_map = {"Air": "plane", "Space": "cloud", "Sea": "info-sign", "Ground": "user"}

# Vẽ Marker & Đường nối sóng không dây cho từng thiết bị biên
for name in selected_node_names:
    node = nodes_dict[name]
    node_info = node.to_dict()

    popup_text = f"""
    <b>{node_info['name']} ({node_info['node_id']})</b><br>
    Tầng vật lý: <b>{node_info['layer']} Layer</b><br>
    Dung lượng Pin: <b>{node_info['battery']}%</b><br>
    Băng thông: <b>{node_info['bandwidth']} Mbps</b><br>
    Trạng thái: <b>{node_info['status']}</b>
    """

    folium.Marker(
        [node_info['lat'], node_info['lon']],
        popup=popup_text,
        icon=folium.Icon(
            color=color_map.get(node_info['layer'], "gray"),
            icon=icon_map.get(node_info['layer'], "info-sign")
        )
    ).add_to(m)

    # 📡 Đường truyền sóng không dây (PolyLine nét đứt) từ Nút biên về Trạm mặt đất
    folium.PolyLine(
        locations=[[gs.lat, gs.lon], [node_info['lat'], node_info['lon']]],
        color=color_map.get(node_info['layer'], "yellow"),
        weight=2.5,
        opacity=0.85,
        dash_array="6, 10"
    ).add_to(m)

folium.LayerControl(position="topright").add_to(m)

# Hiển thị bản đồ Google Maps GIS mở rộng full màn hình trung tâm
st_folium(m, use_container_width=True, height=520)

st.markdown("---")

# =========================================================
# PHẦN 2: KHI CUỘN XUỐNG - BẢNG THÔNG SỐ & HIỆU NĂNG CHI TIẾT
# =========================================================
col_left, col_right = st.columns([1.2, 1])

with col_left:
    st.markdown("### 📋 Bảng Thông Số Chi Tiết Thiết Bị Biên")
    selected_data = [nodes_dict[name].to_dict() for name in selected_node_names]
    if selected_data:
        df_nodes = pd.DataFrame(selected_data)

        # Sắp xếp và chọn các cột thông số hiển thị
        cols_order = ["node_id", "name", "layer", "status", "battery", "bandwidth", "lat", "lon"]
        existing_cols = [c for c in cols_order if c in df_nodes.columns]
        df_nodes = df_nodes[existing_cols]

        # Đổi tên cột sang tiếng Việt cho chuyên nghiệp
        df_nodes = df_nodes.rename(columns={
            "node_id": "Mã Nút",
            "name": "Tên Thiết Bị",
            "layer": "Tầng Mạng",
            "status": "Trạng Thái",
            "battery": "Pin (%)",
            "bandwidth": "Băng Thông (Mbps)",
            "lat": "Vĩ Độ",
            "lon": "Kinh Độ"
        })
        st.dataframe(df_nodes, use_container_width=True, height=280)
    else:
        st.warning("Chưa chọn thiết bị nào trong Sidebar.")

with col_right:
    st.markdown("### 📈 Tiến Trình Hội Tụ Mô Hình AI (FedAvg)")
    rounds = list(range(1, 11))
    acc_data = [12.5, 35.0, 58.2, 72.1, 80.5, 85.3, 88.0, 90.2, 91.5, 92.8]
    loss_data = [2.3, 1.8, 1.4, 1.0, 0.7, 0.5, 0.4, 0.3, 0.25, 0.2]

    df_metrics = pd.DataFrame({
        "Vòng lặp (Round)": rounds,
        "Độ chính xác (%)": acc_data,
        "Độ lỗi (Loss)": loss_data
    }).set_index("Vòng lặp (Round)")

    st.line_chart(df_metrics, height=280)

st.info(
    "💡 Giao diện đã được tối ưu: Bản đồ Google Maps mở rộng nằm ở trung tâm, cuộn xuống dưới để xem toàn bộ thông số thiết bị và hiệu năng hội tụ mô hình.")