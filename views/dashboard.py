import sys
import os

# Thêm thư mục gốc vào Python Path để nhận diện các gói models, database và views
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import folium

# Import các lớp mô hình từ package models
from models import GroundStation, UAV, Satellite, Ship, Vehicle
from database import SAGSINDatabase

# Import 8 hàm render giao diện từ 8 file chức năng trong cùng thư mục views
from views.gis_map import render_gis_map
from views.data_collect import render_data_collect
from views.fl_training import render_fl_training
from views.routing import render_routing
from views.energy_crud import render_energy_crud
from views.attack_defense import render_attack_defense
from views.resource_pso import render_resource_pso
from views.db_admin import render_db_admin

# 1. Cấu hình trang Streamlit Dashboard
st.set_page_config(
    page_title="PBL4 - SAGSINs FL Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Custom CSS: Hiệu ứng Hover Collapsible Sidebar (Di chuột mở rộng)
st.markdown("""
<style>
    /* Trạng thái thu gọn mặc định (rộng 80px) */
    [data-testid="stSidebar"] {
        width: 80px !important;
        min-width: 80px !important;
        transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1) !important;
        overflow-x: hidden !important;
        background-color: #f8fafc !important;
        border-right: 1px solid #e2e8f0 !important;
        box-shadow: 2px 0 10px rgba(0,0,0,0.05);
    }
    /* Mở rộng Sidebar ra 320px khi di chuột hover vào */
    [data-testid="stSidebar"]:hover {
        width: 320px !important;
        min-width: 320px !important;
        box-shadow: 4px 0 20px rgba(0,0,0,0.12);
    }
    /* Ẩn chữ dài khi ở dạng thu gọn */
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] .stRadio label div:nth-child(2) {
        opacity: 0;
        transition: opacity 0.25s ease-in-out;
        white-space: nowrap;
    }
    /* Hiển thị chữ đầy đủ khi hover */
    [data-testid="stSidebar"]:hover [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"]:hover .stRadio label div:nth-child(2) {
        opacity: 1;
    }
</style>
""", unsafe_allow_html=True)

# 3. Khởi tạo Database Engine
db = SAGSINDatabase()

# 4. Khởi tạo danh sách các nút biên trong session state
if 'nodes_list' not in st.session_state:
    st.session_state.nodes_list = [
        UAV(node_id="UAV_DN", name="Drone Giám Sát Đà Nẵng", lat=16.2000, lon=108.3000, battery=95.0, bandwidth=50.0),
        UAV(node_id="UAV_HN", name="Drone Cứu Hộ Hà Nội", lat=21.1000, lon=105.9000, battery=18.0, bandwidth=45.0),
        UAV(node_id="UAV_HS", name="Drone Hải Đảo Hoàng Sa", lat=16.5000, lon=111.5000, battery=92.0, bandwidth=30.0),

        Satellite(node_id="SAT_VN01", name="Vệ Tinh LEO Việt Nam 1", lat=17.5000, lon=107.0000, battery=100.0, bandwidth=25.0, orbit_altitude=600),
        Satellite(node_id="SAT_SEA02", name="Vệ Tinh LEO Đông Nam Á", lat=5.0000, lon=105.0000, battery=98.0, bandwidth=30.0, orbit_altitude=800),

        Ship(node_id="SHIP_DN", name="Tàu Tuần Tra Đà Nẵng", lat=15.8000, lon=108.8000, battery=85.0, bandwidth=15.0),
        Ship(node_id="SHIP_CSB", name="Tàu Cảnh Sát Biển Hoàng Sa", lat=16.2000, lon=112.0000, battery=8.0, bandwidth=20.0),

        Vehicle(node_id="VEH_DN", name="Xe Thông Minh Đà Nẵng", lat=16.0200, lon=108.1800, battery=91.0, bandwidth=100.0),
        Vehicle(node_id="VEH_HN", name="Xe Tự Hành Hà Nội", lat=21.0100, lon=105.8000, battery=89.0, bandwidth=95.0),
    ]

servers_dict = {
    "GS_DANANG": GroundStation(station_id="GS_DANANG", name="Trạm Mặt Đất Đà Nẵng", lat=16.0544, lon=108.2022),
    "GS_HANOI": GroundStation(station_id="GS_HANOI", name="Trạm Mặt Đất Hà Nội", lat=21.0285, lon=105.8542),
    "GS_SINGAPORE": GroundStation(station_id="GS_SINGAPORE", name="Trạm Mặt Đất Singapore", lat=1.3521, lon=103.8198),
}

def create_base_map():
    m = folium.Map(location=[16.0000, 108.5000], zoom_start=6, tiles=None)
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        attr="Google Maps", name="Google Maps (Đường xá - Mặc định)", overlay=False, control=True
    ).add_to(m)
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google Maps", name="Google Maps (Vệ tinh + Địa danh)", overlay=False, control=True
    ).add_to(m)
    return m

# 5. Sidebar Menu
st.sidebar.markdown("### 📡 PBL4 SAGSINs")
st.sidebar.caption("Di Chuột Mở Rộng Menu")
st.sidebar.markdown("---")

menu_options = [
    "🗺️ Giám Sát Mạng GIS Live",
    "📥 Thu Thập Data Cảm Biến",
    "🧠 Train FL & Bảo Mật LDP",
    "📡 Định Tuyến Dijkstra",
    "🔋 Giám Sát Pin & Cứu Hộ Node",
    "🛡️ Mô Phỏng Tấn Công AI",
    "⚡ Phân Bổ Tài Nguyên PSO",
    "🗄️ Quản Trị CSDL SQLite"
]

menu_choice = st.sidebar.radio("MENU CHỨC NĂNG:", menu_options)
nodes_dict = {f"{n.name} ({n.layer} - {n.node_id})": n for n in st.session_state.nodes_list}

# 6. Điều hướng hiển thị giao diện theo lựa chọn của người dùng
if menu_choice == menu_options[0]:
    render_gis_map(servers_dict, st.session_state.nodes_list, create_base_map)
elif menu_choice == menu_options[1]:
    render_data_collect(nodes_dict, db)
elif menu_choice == menu_options[2]:
    render_fl_training(nodes_dict, db)
elif menu_choice == menu_options[3]:
    render_routing(servers_dict, st.session_state.nodes_list, nodes_dict, db, create_base_map)
elif menu_choice == menu_options[4]:
    render_energy_crud(servers_dict, nodes_dict, db)
elif menu_choice == menu_options[5]:
    render_attack_defense()
elif menu_choice == menu_options[6]:
    render_resource_pso(st.session_state.nodes_list)
elif menu_choice == menu_options[7]:
    render_db_admin(db)