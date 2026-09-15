import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

import streamlit as st
import folium

from models import GroundStation, UAV, Satellite, Ship, Vehicle
from database import SAGSINDatabase
from views import (
    render_gis_map, render_data_collect, render_fl_training, render_routing,
    render_energy_crud, render_attack_defense, render_resource_pso, render_db_admin
)

st.set_page_config(
    page_title="PBL4 - SAGSINs FL Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Cấu hình giao diện (Sci-Fi Dashboard CSS)
st.markdown("""
<style>
    :root {
        --bg-color: #0b0f19;
        --panel-bg: rgba(16, 24, 43, 0.7);
        --neon-cyan: #00f3ff;
        --neon-magenta: #ff00e5;
        --neon-purple: #b500ff;
        --text-main: #e2e8f0;
    }
    
    /* Custom Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: rgba(11, 15, 25, 0.8);
    }
    ::-webkit-scrollbar-thumb {
        background: rgba(0, 243, 255, 0.3);
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: rgba(0, 243, 255, 0.8);
    }

    /* Giao diện chính */
    .stApp {
        background-color: var(--bg-color);
        background-image: 
            radial-gradient(circle at 15% 50%, rgba(0, 243, 255, 0.05), transparent 25%),
            radial-gradient(circle at 85% 30%, rgba(255, 0, 229, 0.05), transparent 25%);
        color: var(--text-main);
        font-family: 'Inter', 'Roboto', sans-serif;
    }
    
    /* Animation mượt mà */
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(15px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0e1422 0%, #080b12 100%) !important;
        border-right: 1px solid rgba(0, 243, 255, 0.2) !important;
        box-shadow: 2px 0 20px rgba(0, 243, 255, 0.08);
    }
    
    [data-testid="stSidebarNav"] {
        display: none;
    }
    
    /* Các Panel / Container hiển thị trong app */
    .sci-fi-panel {
        background: var(--panel-bg);
        border: 1px solid rgba(0, 243, 255, 0.2);
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3), inset 0 0 20px rgba(0, 243, 255, 0.02);
        backdrop-filter: blur(12px);
        margin-bottom: 24px;
        transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        animation: fadeInUp 0.6s ease-out forwards;
    }
    
    .sci-fi-panel:hover {
        border-color: rgba(0, 243, 255, 0.6);
        box-shadow: 0 8px 25px rgba(0, 243, 255, 0.2), inset 0 0 20px rgba(0, 243, 255, 0.05);
        transform: translateY(-4px) scale(1.005);
    }
    
    /* Typography */
    h1, h2, h3, h4, h5, h6 {
        color: #fff !important;
        text-shadow: 0 0 10px rgba(0, 243, 255, 0.3);
    }
    
    .glow-text {
        color: var(--neon-cyan);
        text-shadow: 0 0 5px var(--neon-cyan);
        font-weight: bold;
    }
    
    /* Streamlit UI Overrides */
    div[data-baseweb="select"] > div {
        background-color: rgba(16, 24, 43, 0.8) !important;
        border: 1px solid rgba(0, 243, 255, 0.3) !important;
        color: white !important;
    }
    
    .stButton>button {
        background: transparent !important;
        border: 1px solid var(--neon-cyan) !important;
        color: var(--neon-cyan) !important;
        border-radius: 20px;
        transition: all 0.3s ease;
        letter-spacing: 1px;
        box-shadow: 0 0 5px rgba(0, 243, 255, 0.2);
    }
    
    .stButton>button:hover {
        background: rgba(0, 243, 255, 0.1) !important;
        box-shadow: 0 0 15px rgba(0, 243, 255, 0.5), inset 0 0 10px rgba(0, 243, 255, 0.2);
        color: #fff !important;
    }
    
    /* Cấu hình đặc biệt cho Sidebar Menu Buttons */
    [data-testid="stSidebar"] .stButton>button {
        justify-content: flex-start !important;
        padding-left: 15px !important;
        border-radius: 8px !important;
        text-transform: none !important;
        letter-spacing: normal !important;
        width: 100% !important;
    }
    
    /* Trạng thái nút Sidebar Không Active */
    [data-testid="stSidebar"] [data-testid="baseButton-secondary"] {
        background: transparent !important;
        border: 1px solid transparent !important;
        color: #94a3b8 !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] [data-testid="baseButton-secondary"]:hover {
        background: rgba(0, 243, 255, 0.05) !important;
        border: 1px solid rgba(0, 243, 255, 0.3) !important;
        color: #fff !important;
    }
    
    /* Trạng thái nút Sidebar Active (Primary) */
    [data-testid="stSidebar"] [data-testid="baseButton-primary"] {
        background: linear-gradient(90deg, rgba(0, 243, 255, 0.2) 0%, transparent 100%) !important;
        border: 1px solid transparent !important;
        border-left: 4px solid var(--neon-cyan) !important;
        color: #fff !important;
        font-weight: bold;
        box-shadow: none !important;
    }
    
    .stSlider > div > div > div > div {
        background: var(--neon-purple) !important;
    }
    
    /* Bảng Dataframe */
    [data-testid="stDataFrame"] {
        border: 1px solid rgba(255, 0, 229, 0.3);
        border-radius: 5px;
    }
    
    /* Header thông số tổng quan (Dashboard) */
    .dashboard-header {
        display: flex;
        justify-content: space-between;
        background: rgba(16, 24, 43, 0.85);
        border: 1px solid rgba(0, 243, 255, 0.2);
        border-radius: 12px;
        padding: 15px 25px;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        backdrop-filter: blur(10px);
        animation: fadeInUp 0.5s ease-out forwards;
    }
    .metric-box {
        text-align: center;
        border-right: 1px solid rgba(255, 255, 255, 0.08);
        padding: 0 20px;
        flex: 1;
        transition: transform 0.3s ease;
    }
    .metric-box:hover {
        transform: translateY(-3px);
    }
    .metric-box:last-child {
        border-right: none;
    }
    .metric-label {
        font-size: 0.85em;
        color: #94a3b8;
        text-transform: uppercase;
    }
    .metric-value {
        font-size: 1.2em;
        font-weight: bold;
        color: var(--neon-cyan);
        text-shadow: 0 0 5px rgba(0, 243, 255, 0.5);
    }
    .metric-value.completed {
        color: #00ff88;
        text-shadow: 0 0 5px rgba(0, 255, 136, 0.5);
    }
</style>
""", unsafe_allow_html=True)

db = SAGSINDatabase()

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

st.sidebar.markdown("<h3 class='glow-text'>🚀 SIMULATION CONTROLS</h3>", unsafe_allow_html=True)
st.sidebar.caption("FL-SAGSIN Simulator Menu")
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

if 'current_menu' not in st.session_state:
    st.session_state.current_menu = menu_options[0]

st.sidebar.markdown("<p style='color: #94a3b8; font-size: 0.9em; font-weight: bold;'>CHỨC NĂNG (DASHBOARD PANELS)</p>", unsafe_allow_html=True)
for option in menu_options:
    is_active = st.session_state.current_menu == option
    if st.sidebar.button(option, key=f"btn_{option}", use_container_width=True, type="primary" if is_active else "secondary"):
        st.session_state.current_menu = option
        st.rerun()

menu_choice = st.session_state.current_menu
nodes_dict = {f"{n.name} ({n.layer} - {n.node_id})": n for n in st.session_state.nodes_list}

# Header Dashboard (Global)
st.markdown("""
<div class="dashboard-header">
    <div class="metric-box">
        <div class="metric-label">Simulation Status</div>
        <div class="metric-value completed">Completed</div>
    </div>
    <div class="metric-box">
        <div class="metric-label">Rounds</div>
        <div class="metric-value">40/40</div>
    </div>
    <div class="metric-box">
        <div class="metric-label">Avg. Local Accuracy</div>
        <div class="metric-value">78%</div>
    </div>
    <div class="metric-box">
        <div class="metric-label">Global Accuracy</div>
        <div class="metric-value">74%</div>
    </div>
    <div class="metric-box">
        <div class="metric-label">Total Time</div>
        <div class="metric-value">125s</div>
    </div>
</div>
""", unsafe_allow_html=True)

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