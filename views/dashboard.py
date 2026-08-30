import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd

# Import các đối tượng từ gói models vừa tách
from models import GroundStation, UAV, Satellite, Ship, Vehicle

# Cấu hình trang Dashboard
st.set_page_config(
    page_title="PBL4 - SAGSINs Federated Learning Dashboard",
    page_icon="📡",
    layout="wide"
)

st.title("📡 MÔ PHỎNG FEDERATED LEARNING TRONG MẠNG TÍCH HỢP SAGSINs")
st.subheader("Đồ án Dự án Hệ điều hành & Mạng máy tính (PBL4)")

# Khởi tạo các thực thể mạng SAGSINs
gs = GroundStation(station_id="GS_DANANG", name="Trạm Mặt Đất Đà Nẵng", lat=16.0544, lon=108.2022)
uav = UAV(node_id="UAV_01", name="Drone Giám Sát", lat=16.2000, lon=108.3000, battery=95.0)
sat = Satellite(node_id="SAT_01", name="Vệ Tinh LEO", lat=16.8000, lon=107.8000, battery=100.0, orbit_altitude=800)
ship = Ship(node_id="SHIP_01", name="Tàu Biển Hải Quân", lat=15.8000, lon=108.8000, battery=88.0)
vehicle = Vehicle(node_id="VEH_01", name="Xe Tự Hành Xe Thông Minh", lat=16.0200, lon=108.1800, battery=90.0)

# Sidebar cấu hình kịch bản
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

# Chia giao diện làm 2 cột
col1, col2 = st.columns([1.2, 1])

with col1:
    st.markdown("### 🗺️ Bản đồ Mạng Tích hợp SAGSINs (GIS Live)")

    # Bản đồ trung tâm tại Trạm mặt đất
    m = folium.Map(location=[gs.lat, gs.lon], zoom_start=8, tiles="OpenStreetMap")

    # Marker Trạm Mặt Đất (Server Trung tâm)
    folium.Marker(
        [gs.lat, gs.lon],
        popup=f"<b>{gs.name}</b><br>Trạng thái: Central Aggregator",
        icon=folium.Icon(color="red", icon="home")
    ).add_to(m)

    # Hiển thị các nút biên được chọn lên bản đồ
    color_map = {"Air": "green", "Space": "blue", "Sea": "orange", "Ground": "purple"}
    icon_map = {"Air": "plane", "Space": "cloud", "Sea": "info-sign", "Ground": "user"}

    for name in selected_node_names:
        node = nodes_dict[name]
        node_info = node.to_dict()

        popup_text = f"""
        <b>{node_info['name']} ({node_info['node_id']})</b><br>
        Tầng: <b>{node_info['layer']}</b><br>
        Pin: {node_info['battery']}% | Băng thông: {node_info['bandwidth']} Mbps<br>
        Trạng thái: {node_info['status']}
        """

        folium.Marker(
            [node_info['lat'], node_info['lon']],
            popup=popup_text,
            icon=folium.Icon(color=color_map.get(node_info['layer'], "gray"),
                             icon=icon_map.get(node_info['layer'], "info-sign"))
        ).add_to(m)

    st_folium(m, width=600, height=450)

with col2:
    st.markdown("### 📊 Thông số Hoạt động & Hiệu năng")

    # Hiển thị bảng tổng hợp thông số nút biên
    selected_data = [nodes_dict[name].to_dict() for name in selected_node_names]
    if selected_data:
        df_nodes = pd.DataFrame(selected_data)[["node_id", "name", "layer", "battery", "bandwidth", "status"]]
        st.dataframe(df_nodes, use_container_width=True)

    # Biểu đồ mô phỏng quá trình hội tụ mô hình AI
    st.markdown("#### Progress Metrics (FedAvg Convergence)")
    rounds = list(range(1, 11))
    acc_data = [12.5, 35.0, 58.2, 72.1, 80.5, 85.3, 88.0, 90.2, 91.5, 92.8]

    df_metrics = pd.DataFrame({
        "Vòng lặp (Round)": rounds,
        "Độ chính xác (%)": acc_data
    }).set_index("Vòng lặp (Round)")

    st.line_chart(df_metrics)

st.info("💡 Hệ thống đã tích hợp đầy đủ 4 tầng mạng vật lý SAGSINs (Space - Air - Ground - Sea).")