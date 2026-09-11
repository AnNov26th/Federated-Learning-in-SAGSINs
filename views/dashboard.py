import sys
import os

# BẮT BỘC: Thêm thư mục gốc vào Python Path để Streamlit Cloud nhận diện gói models
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd

# Import các lớp mô hình OOP
from models import GroundStation, UAV, Satellite, Ship, Vehicle

# 1. Cấu hình trang Dashboard
st.set_page_config(
    page_title="PBL4 - Multi-Region SAGSINs FL Dashboard",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 MÔ PHỎNG HỌC LIÊN HỢP PHÂN TẦNG TRONG MẠNG SAGSINs TOÀN CẦU")
st.subheader("Đồ án Dự án Hệ điều hành & Mạng máy tính (PBL4) - Mô hình Multi-Server & Multi-Node")

# =========================================================
# 2. KHỞI TẠO DANH SÁCH ĐA SERVER TRẠM MẶT ĐẤT (REGIONAL SERVERS)
# =========================================================
servers_dict = {
    "GS_DANANG": GroundStation(station_id="GS_DANANG", name="Trạm Mặt Đất Đà Nẵng", lat=16.0544, lon=108.2022),
    "GS_HANOI": GroundStation(station_id="GS_HANOI", name="Trạm Mặt Đất Hà Nội", lat=21.0285, lon=105.8542),
    "GS_SINGAPORE": GroundStation(station_id="GS_SINGAPORE", name="Trạm Mặt Đất Singapore", lat=1.3521, lon=103.8198),
    "GS_TOKYO": GroundStation(station_id="GS_TOKYO", name="Trạm Mặt Đất Tokyo", lat=35.6762, lon=139.6503)
}

# =========================================================
# 3. KHỞI TẠO DANH SÁCH ĐA THỰC THỂ BIÊN (DISTRIBUTED EDGE NODES)
# =========================================================
nodes_list = [
    # --- Tầng Air (UAVs) ---
    UAV(node_id="UAV_DN", name="Drone Giám Sát Đà Nẵng", lat=16.2000, lon=108.3000, battery=95.0, bandwidth=50.0),
    UAV(node_id="UAV_HN", name="Drone Cứu Hộ Hà Nội", lat=21.1000, lon=105.9000, battery=88.0, bandwidth=45.0),
    UAV(node_id="UAV_HS", name="Drone Hải Đảo Hoàng Sa", lat=16.5000, lon=111.5000, battery=92.0, bandwidth=30.0),

    # --- Tầng Space (Satellites) ---
    Satellite(node_id="SAT_VN01", name="Vệ Tinh LEO Việt Nam 1", lat=17.5000, lon=107.0000, battery=100.0,
              bandwidth=25.0, orbit_altitude=600),
    Satellite(node_id="SAT_SEA02", name="Vệ Tinh LEO Đông Nam Á", lat=5.0000, lon=105.0000, battery=98.0,
              bandwidth=30.0, orbit_altitude=800),
    Satellite(node_id="SAT_ASIA03", name="Vệ Tinh Viễn Thám Đông Bắc Á", lat=30.0000, lon=130.0000, battery=96.0,
              bandwidth=40.0, orbit_altitude=750),

    # --- Tầng Sea (Ships) ---
    Ship(node_id="SHIP_DN", name="Tàu Tuần Tra Đà Nẵng", lat=15.8000, lon=108.8000, battery=85.0, bandwidth=15.0),
    Ship(node_id="SHIP_CSB", name="Tàu Cảnh Sát Biển Hoàng Sa", lat=16.2000, lon=112.0000, battery=90.0,
         bandwidth=20.0),
    Ship(node_id="SHIP_SG", name="Tàu Vận Tải Singapore", lat=1.8000, lon=104.5000, battery=82.0, bandwidth=18.0),

    # --- Tầng Ground (Vehicles) ---
    Vehicle(node_id="VEH_DN", name="Xe Thông Minh Đà Nẵng", lat=16.0200, lon=108.1800, battery=91.0, bandwidth=100.0),
    Vehicle(node_id="VEH_HN", name="Xe Tự Hành Hà Nội", lat=21.0100, lon=105.8000, battery=89.0, bandwidth=95.0),
]

# Tạo dictionary quản lý nút biên
nodes_dict = {f"{n.name} ({n.layer} - {n.node_id})": n for n in nodes_list}


# Hàm tìm Trạm Mặt Đất gần nhất cho mỗi nút biên
def get_nearest_server(node_lat, node_lon, servers):
    min_dist = float('inf')
    nearest_server = None
    for s_id, server in servers.items():
        # Tính khoảng cách xấp xỉ theo bình phương kinh vĩ độ
        dist = (node_lat - server.lat) ** 2 + (node_lon - server.lon) ** 2
        if dist < min_dist:
            min_dist = dist
            nearest_server = server
    return nearest_server


# =========================================================
# 4. SIDEBAR CẤU HÌNH ĐA THỰC THỂ
# =========================================================
st.sidebar.header("⚙️ Cấu Hình Mạng Đa Server & Đa Nút")

# Chọn các Trạm Mặt Đất tham gia
selected_server_ids = st.sidebar.multiselect(
    "🏠 Chọn Máy chủ Trạm Mặt Đất hoạt động:",
    list(servers_dict.keys()),
    default=list(servers_dict.keys())
)

# Chọn các Nút biên tham gia
selected_node_keys = st.sidebar.multiselect(
    "📡 Chọn Nút biên tham gia Học liên hợp:",
    list(nodes_dict.keys()),
    default=list(nodes_dict.keys())
)

num_rounds = st.sidebar.slider("Số vòng huấn luyện (Global Rounds)", 5, 50, 15)

# =========================================================
# PHẦN 1: BẢN ĐỒ MẠNG TOÀN CẦU (GOOGLE MAPS GIS LIVE)
# =========================================================
st.markdown("### 🗺️ Bản Đồ Mạng SAGSINs Toàn Cầu (Multi-Server GIS Live)")

# Tạo bản đồ trung tâm tại khu vực Biển Đông / Đông Nam Á
m = folium.Map(
    location=[16.0000, 110.0000],
    zoom_start=5,
    tiles=None
)

# Thêm lớp Google Maps Hybrid (Vệ tinh + Tên địa danh)
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attr="Google Maps",
    name="Google Maps (Vệ tinh + Địa danh)",
    overlay=False,
    control=True
).add_to(m)

# Thêm lớp Google Maps Roadmap
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
    attr="Google Maps",
    name="Google Maps (Đường xá)",
    overlay=False,
    control=True
).add_to(m)

# Thêm lớp Dark Mode
folium.TileLayer(
    tiles="CartoDB dark_matter",
    attr="CartoDB",
    name="Giao diện Tối (Dark Mode)",
    overlay=False,
    control=True
).add_to(m)

# 1. Vẽ Marker cho các Trạm Mặt Đất (Servers) được chọn
active_servers = {s_id: servers_dict[s_id] for s_id in selected_server_ids}

for s_id, server in active_servers.items():
    server_popup_html = f"""
    <div style="width: 250px; font-size: 13px; line-height: 1.6;">
        <b style="font-size: 14px; color: #d9534f;">🏠 {server.name} ({server.station_id})</b><br>
        <b>Vai trò:</b> Regional Aggregator Server<br>
        <b>Tọa độ:</b> {server.lat}, {server.lon}<br>
        <b>Trạng thái:</b> <span style="color: green; font-weight: bold;">ACTIVE</span>
    </div>
    """
    folium.Marker(
        [server.lat, server.lon],
        popup=folium.Popup(server_popup_html, max_width=300),
        icon=folium.Icon(color="red", icon="home", prefix="fa")
    ).add_to(m)

# 2. Vẽ Marker và Đường truyền sóng cho các Nút biên (Clients)
color_map = {"Air": "green", "Space": "blue", "Sea": "orange", "Ground": "purple"}
icon_map = {"Air": "plane", "Space": "cloud", "Sea": "info-sign", "Ground": "user"}

for key in selected_node_keys:
    node = nodes_dict[key]
    node_info = node.to_dict()

    # Tìm Trạm Mặt Đất gần nhất cho nút biên này
    assigned_server = get_nearest_server(node_info['lat'], node_info['lon'], active_servers) if active_servers else None

    server_conn_str = f"{assigned_server.name}" if assigned_server else "Chưa gán Server"

    node_popup_html = f"""
    <div style="width: 250px; font-size: 13px; line-height: 1.7;">
        <b style="font-size: 14px; color: #0275d8;">{node_info['name']} ({node_info['node_id']})</b><br>
        <b>Tầng vật lý:</b> {node_info['layer']} Layer<br>
        <b>Kết nối đến:</b> <span style="color: #d9534f; font-weight: bold;">{server_conn_str}</span><br>
        <b>Dung lượng Pin:</b> {node_info['battery']}%<br>
        <b>Băng thông:</b> {node_info['bandwidth']} Mbps<br>
        <b>Trạng thái:</b> <span style="color: green; font-weight: bold;">{node_info['status']}</span>
    </div>
    """

    folium.Marker(
        [node_info['lat'], node_info['lon']],
        popup=folium.Popup(node_popup_html, max_width=300),
        icon=folium.Icon(
            color=color_map.get(node_info['layer'], "gray"),
            icon=icon_map.get(node_info['layer'], "info-sign")
        )
    ).add_to(m)

    # 📡 Nối đường sóng không dây nét đứt từ Nút biên về Trạm Mặt Đất gần nhất
    if assigned_server:
        folium.PolyLine(
            locations=[[assigned_server.lat, assigned_server.lon], [node_info['lat'], node_info['lon']]],
            color=color_map.get(node_info['layer'], "yellow"),
            weight=2.0,
            opacity=0.8,
            dash_array="5, 8"
        ).add_to(m)

folium.LayerControl(position="topright").add_to(m)
st_folium(m, use_container_width=True, height=540)

st.markdown("---")

# =========================================================
# PHẦN 2: KHI CUỘN XUỐNG - BẢNG THÔNG SỐ ĐA THỰC THỂ & HIỆU NĂNG
# =========================================================
col_left, col_right = st.columns([1.3, 1])

with col_left:
    st.markdown("### 📋 Danh Sách & Thông Số Các Nút Biên Vùng")
    selected_data = []
    for key in selected_node_keys:
        node = nodes_dict[key]
        info = node.to_dict()
        nearest_srv = get_nearest_server(info['lat'], info['lon'], active_servers) if active_servers else None
        info['assigned_server'] = nearest_srv.name if nearest_srv else "N/A"
        selected_data.append(info)

    if selected_data:
        df_nodes = pd.DataFrame(selected_data)

        cols_order = ["node_id", "name", "layer", "assigned_server", "status", "battery", "bandwidth", "lat", "lon"]
        existing_cols = [c for c in cols_order if c in df_nodes.columns]
        df_nodes = df_nodes[existing_cols]

        df_nodes = df_nodes.rename(columns={
            "node_id": "Mã Nút",
            "name": "Tên Thiết Bị",
            "layer": "Tầng Mạng",
            "assigned_server": "Server Phụ Trách",
            "status": "Trạng Thái",
            "battery": "Pin (%)",
            "bandwidth": "Băng Thông (Mbps)",
            "lat": "Vĩ Độ",
            "lon": "Kinh Độ"
        })
        st.dataframe(df_nodes, use_container_width=True, height=320)
    else:
        st.warning("Chưa chọn thiết bị nào trong Sidebar.")

with col_right:
    st.markdown("### 📈 Tiến Trình Hội Tụ Hierarchical FedAvg")
    rounds = list(range(1, num_rounds + 1))

    # Giả lập dữ liệu hội tụ tăng dần
    import numpy as np

    acc_base = 15.0 + 78.0 * (1 - np.exp(-0.25 * np.array(rounds)))
    loss_base = 2.5 * np.exp(-0.22 * np.array(rounds))

    df_metrics = pd.DataFrame({
        "Vòng lặp (Round)": rounds,
        "Độ chính xác toàn cục (%)": np.round(acc_base, 2),
        "Độ lỗi (Global Loss)": np.round(loss_base, 3)
    }).set_index("Vòng lặp (Round)")

    st.line_chart(df_metrics, height=320)

st.info(
    "💡 Mạng SAGSINs đa vùng đã được cấu hình: Tự động gán nút biên về Trạm Mặt Đất gần nhất, hiển thị đường nối sóng không dây và bảng thông số toàn cầu.")
