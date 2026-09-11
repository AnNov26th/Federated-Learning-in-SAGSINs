import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
import random

from models import GroundStation, UAV, Satellite, Ship, Vehicle
from database import SAGSINDatabase
from models.mobility import MobilityEngine
from models.routing import SAGSINRoutingEngine

st.set_page_config(
    page_title="PBL4 - SAGSINs FL & GIS Routing Dashboard",
    page_icon="🌍",
    layout="wide"
)

db = SAGSINDatabase()

st.title("🌍 HỆ THỐNG MÔ PHỎNG SAGSINs: TỰ ĐỘNG THU THẬP, HỌC LIÊN HỢP & ĐỊNH TUYẾN TỐI ƯU")
st.subheader("Đồ án Dự án Hệ điều hành & Mạng máy tính (PBL4)")

if 'nodes_state' not in st.session_state:
    st.session_state.nodes_list = [
        UAV(node_id="UAV_DN", name="Drone Giám Sát Đà Nẵng", lat=16.2000, lon=108.3000, battery=95.0, bandwidth=50.0),
        UAV(node_id="UAV_HN", name="Drone Cứu Hộ Hà Nội", lat=21.1000, lon=105.9000, battery=88.0, bandwidth=45.0),
        UAV(node_id="UAV_HS", name="Drone Hải Đảo Hoàng Sa", lat=16.5000, lon=111.5000, battery=92.0, bandwidth=30.0),

        Satellite(node_id="SAT_VN01", name="Vệ Tinh LEO Việt Nam 1", lat=17.5000, lon=107.0000, battery=100.0,
                  bandwidth=25.0, orbit_altitude=600),
        Satellite(node_id="SAT_SEA02", name="Vệ Tinh LEO Đông Nam Á", lat=5.0000, lon=105.0000, battery=98.0,
                  bandwidth=30.0, orbit_altitude=800),

        Ship(node_id="SHIP_DN", name="Tàu Tuần Tra Đà Nẵng", lat=15.8000, lon=108.8000, battery=85.0, bandwidth=15.0),
        Ship(node_id="SHIP_CSB", name="Tàu Cảnh Sát Biển Hoàng Sa", lat=16.2000, lon=112.0000, battery=90.0,
             bandwidth=20.0),

        Vehicle(node_id="VEH_DN", name="Xe Thông Minh Đà Nẵng", lat=16.0200, lon=108.1800, battery=91.0,
                bandwidth=100.0),
        Vehicle(node_id="VEH_HN", name="Xe Tự Hành Hà Nội", lat=21.0100, lon=105.8000, battery=89.0, bandwidth=95.0),
    ]
    st.session_state.nodes_state = True

servers_dict = {
    "GS_DANANG": GroundStation(station_id="GS_DANANG", name="Trạm Mặt Đất Đà Nẵng", lat=16.0544, lon=108.2022),
    "GS_HANOI": GroundStation(station_id="GS_HANOI", name="Trạm Mặt Đất Hà Nội", lat=21.0285, lon=105.8542),
    "GS_SINGAPORE": GroundStation(station_id="GS_SINGAPORE", name="Trạm Mặt Đất Singapore", lat=1.3521, lon=103.8198),
}

nodes_dict = {f"{n.name} ({n.layer} - {n.node_id})": n for n in st.session_state.nodes_list}

st.sidebar.header("⚙️ Điều Khiển Simulation")

selected_server_ids = st.sidebar.multiselect(
    "🏠 Chọn Máy chủ Trạm Mặt Đất:",
    list(servers_dict.keys()),
    default=list(servers_dict.keys())
)

selected_node_keys = st.sidebar.multiselect(
    "📡 Chọn Nút biên hoạt động:",
    list(nodes_dict.keys()),
    default=list(nodes_dict.keys())
)

privacy_epsilon = st.sidebar.slider("🔒 Ngân sách Bảo mật Privacy Budget (ε):", 0.1, 10.0, 2.0)

st.sidebar.markdown("---")
st.sidebar.subheader("🎮 Thao tác Giả lập")

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    btn_collect = st.button("📥 Thu Nhập Data", use_container_width=True)
    btn_train = st.button("🧠 Train & Gửi FL", use_container_width=True)
with col_btn2:
    btn_move = st.button("🛸 Di Chuyển Nút", use_container_width=True)
    btn_route = st.button("📡 Tìm Route Nhanh", use_container_width=True)

if btn_collect:
    sensor_types = {
        "Air": ("Ảnh Hồng Ngoại UAV", 150, "Chụp giám sát diện rộng"),
        "Space": ("Ảnh Viễn Thám Vệ Tinh", 500, "Ảnh radar đa phổ không gian"),
        "Sea": ("Tín Hiệu Sóng Âm Sonar", 200, "Cảm biến hải trình & lòng biển"),
        "Ground": ("Video Camera Giao Thông", 350, "Lưu lượng xe cộ đô thị")
    }
    for k in selected_node_keys:
        node = nodes_dict[k]
        dtype, samples, desc = sensor_types.get(node.layer, ("Dữ liệu Cảm Biến", 100, "Dữ liệu thô"))
        db.insert_collected_data(node.node_id, node.name, node.layer, dtype, samples + random.randint(-20, 50), desc)
    st.sidebar.success("✅ Đã tự động thu thập & lưu dữ liệu vào Database SQLite!")

if btn_train:
    for k in selected_node_keys:
        node = nodes_dict[k]
        loss = round(random.uniform(0.15, 0.85), 3)
        acc = round(random.uniform(82.0, 96.5), 2)
        weight_kb = round(random.uniform(1200.0, 2500.0), 1)
        db.insert_training_log(random.randint(1, 10), node.node_id, node.name, loss, acc, privacy_epsilon, weight_kb)
    st.sidebar.success("✅ Các nút đã Train cục bộ, chèn nhiễu LDP & gửi trọng số về Server!")

if btn_move:
    MobilityEngine.update_positions(st.session_state.nodes_list, step_time=1.0)
    st.sidebar.info("🛸 Đã cập nhật tọa độ di chuyển thực tế!")

st.markdown("### 🗺️ Bản Đồ Trực Quan Mạng SAGSINs & Định Tuyến Thông Tin")

# Tạo bản đồ với Google Maps Đường Xá làm MẶC ĐỊNH
m = folium.Map(
    location=[16.0000, 108.5000],
    zoom_start=6,
    tiles=None
)

# 1. Google Maps Roadmap (Mặc định)
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
    attr="Google Maps",
    name="Google Maps (Đường xá - Mặc định)",
    overlay=False,
    control=True
).add_to(m)

# 2. Google Maps Hybrid (Vệ tinh + Địa danh)
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attr="Google Maps",
    name="Google Maps (Vệ tinh + Địa danh)",
    overlay=False,
    control=True
).add_to(m)

active_servers = {s_id: servers_dict[s_id] for s_id in selected_server_ids}

for s_id, server in active_servers.items():
    server_popup = f"""
    <div style="width: 240px; font-size: 13px; line-height: 1.6;">
        <b style="font-size: 14px; color: #d9534f;">🏠 {server.name} ({server.station_id})</b><br>
        <b>Vai trò:</b> Regional Aggregator Server<br>
        <b>Tọa độ:</b> {server.lat:.4f}, {server.lon:.4f}
    </div>
    """
    folium.Marker(
        [server.lat, server.lon],
        popup=folium.Popup(server_popup, max_width=300),
        icon=folium.Icon(color="red", icon="home")
    ).add_to(m)

color_map = {"Air": "green", "Space": "blue", "Sea": "orange", "Ground": "purple"}
icon_map = {"Air": "plane", "Space": "cloud", "Sea": "info-sign", "Ground": "user"}

all_entities_data = []
for s_id, s in active_servers.items():
    all_entities_data.append(
        {'id': s_id, 'name': s.name, 'lat': s.lat, 'lon': s.lon, 'layer': 'GroundServer', 'bandwidth': 1000.0})

for key in selected_node_keys:
    node = nodes_dict[key]
    info = node.to_dict()
    all_entities_data.append(
        {'id': info['node_id'], 'name': info['name'], 'lat': info['lat'], 'lon': info['lon'], 'layer': info['layer'],
         'bandwidth': info['bandwidth'], 'orbit_altitude': getattr(node, 'orbit_altitude', 0)})

    popup_html = f"""
    <div style="width: 240px; font-size: 13px; line-height: 1.7;">
        <b style="font-size: 14px; color: #0275d8;">{info['name']} ({info['node_id']})</b><br>
        <b>Tầng vật lý:</b> {info['layer']} Layer<br>
        <b>Pin:</b> {info['battery']}% | <b>Băng thông:</b> {info['bandwidth']} Mbps<br>
        <b>Tọa độ:</b> {info['lat']:.4f}, {info['lon']:.4f}
    </div>
    """
    folium.Marker(
        [info['lat'], info['lon']],
        popup=folium.Popup(popup_html, max_width=300),
        icon=folium.Icon(color=color_map.get(info['layer'], "gray"), icon=icon_map.get(info['layer'], "info-sign"))
    ).add_to(m)

# Xử lý Định tuyến Tuyến Nhanh Nhất (Auto Route Dijkstra)
if btn_route and len(selected_node_keys) > 0 and len(selected_server_ids) > 0:
    src_key = selected_node_keys[0]
    src_node = nodes_dict[src_key]
    target_server_id = selected_server_ids[0]

    path, total_latency, bw = SAGSINRoutingEngine.find_optimal_route(all_entities_data, src_node.node_id,
                                                                     target_server_id)

    if path and len(path) > 1:
        path_coords = []
        path_names = []
        entity_lookup = {e['id']: e for e in all_entities_data}

        for hop_id in path:
            e = entity_lookup[hop_id]
            path_coords.append([e['lat'], e['lon']])
            path_names.append(e['name'])

        folium.PolyLine(
            locations=path_coords,
            color="red",
            weight=4.5,
            opacity=0.9,
            popup=f"Tuyến nhanh nhất: {' -> '.join(path_names)} (Độ trễ: {total_latency:.2f} ms)"
        ).add_to(m)

        path_str = " ➔ ".join(path_names)
        db.insert_routing_log(src_node.name, active_servers[target_server_id].name, path_str, total_latency, bw)
        st.success(
            f"🚀 **ĐÃ TÌM THẤY TUYẾN NHANH NHẤT:** {path_str} | **Tổng độ trễ:** {total_latency:.2f} ms | **Băng thông:** {bw} Mbps")

folium.LayerControl(position="topright").add_to(m)
st_folium(m, use_container_width=True, height=520)

st.markdown("---")

st.markdown("### 🗄️ Cơ Sở Dữ Liệu Hệ Thống SQLite (Database Logs)")

tab1, tab2, tab3, tab4 = st.tabs([
    "📥 Dữ Liệu Thu Thập Cục Bộ",
    "🧠 Nhật Ký Huấn Luyện FL",
    "📡 Lịch Sử Định Tuyến Nhanh Nhất",
    "📊 Tiến Trình Hội Tụ (FedAvg)"
])

with tab1:
    df_data = db.fetch_collected_data()
    if not df_data.empty:
        df_data = df_data.rename(columns={
            "id": "STT", "node_id": "Mã Nút", "node_name": "Tên Thiết Bị",
            "layer": "Tầng Mạng", "data_type": "Loại Dữ Liệu",
            "data_samples": "Số Mẫu", "description": "Mô Tả", "timestamp": "Thời Gian"
        })
        st.dataframe(df_data, use_container_width=True, height=280)
    else:
        st.info("Chưa có dữ liệu thô. Nhấn nút '📥 Thu Nhập Data' trên Sidebar để giả lập!")

with tab2:
    df_train = db.fetch_training_logs()
    if not df_train.empty:
        df_train = df_train.rename(columns={
            "id": "STT", "round": "Vòng FL", "node_id": "Mã Nút", "node_name": "Tên Thiết Bị",
            "local_loss": "Độ Lỗi (Loss)", "local_accuracy": "Độ Chính Xác (%)",
            "privacy_epsilon": "Ngân Sách Epsilon (ε)", "weight_size_kb": "Dung Lượng (KB)", "timestamp": "Thời Gian"
        })
        st.dataframe(df_train, use_container_width=True, height=280)
    else:
        st.info("Chưa có nhật ký huấn luyện. Nhấn nút '🧠 Train & Gửi FL' để mô phỏng!")

with tab3:
    df_route = db.fetch_routing_logs()
    if not df_route.empty:
        df_route = df_route.rename(columns={
            "id": "STT", "source_node": "Nút Nguồn", "target_server": "Server Đích",
            "path_hops": "Tuyến Đường (Hops)", "total_latency_ms": "Tổng Độ Trễ (ms)",
            "bottleneck_bw_mbps": "Băng Thông (Mbps)", "timestamp": "Thời Gian"
        })
        st.dataframe(df_route, use_container_width=True, height=280)
    else:
        st.info("Chưa có lịch sử định tuyến. Nhấn nút '📡 Tìm Route Nhanh' để tính toán!")

with tab4:
    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        rounds = list(range(1, 11))
        acc_vals = [15.2, 38.5, 62.1, 75.8, 83.2, 87.9, 90.5, 92.3, 93.8, 94.7]
        df_acc = pd.DataFrame({"Vòng FL": rounds, "Độ chính xác (%)": acc_vals}).set_index("Vòng FL")
        st.line_chart(df_acc, height=260)
    with col_chart2:
        loss_vals = [2.45, 1.82, 1.25, 0.88, 0.58, 0.42, 0.31, 0.24, 0.19, 0.15]
        df_loss = pd.DataFrame({"Vòng FL": rounds, "Độ lỗi (Loss)": loss_vals}).set_index("Vòng FL")
        st.line_chart(df_loss, height=260)

st.info(
    "💡 Hệ thống đã được tích hợp đầy đủ Database SQLite, Tìm tuyến nhanh nhất Dijkstra, Di chuyển tọa độ thực tế và Mặc định Google Maps Đường xá.")