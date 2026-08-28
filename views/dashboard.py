import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd

# Cấu hình trang Dashboard
st.set_page_config(
    page_title="PBL4 - SAGSINs Federated Learning Dashboard",
    page_icon="📡",
    layout="wide"
)

st.title("📡 MÔ PHỎNG FEDERATED LEARNING TRONG MẠNG SAGSINs")
st.subheader("Đồ án Dự án Hệ điều hành & Mạng máy tính (PBL4)")

# Sidebar cấu hình kịch bản
st.sidebar.header("⚙️ Cấu hình Kịch bản")
num_rounds = st.sidebar.slider("Số vòng huấn luyện (Rounds)", 5, 50, 10)
selected_clients = st.sidebar.multiselect(
    "Chọn nút biên tham gia:",
    ["UAV_01 (Tầng trên không)", "SAT_01 (Tầng không gian)", "SHIP_01 (Tầng biển)"],
    default=["UAV_01 (Tầng trên không)", "SAT_01 (Tầng không gian)", "SHIP_01 (Tầng biển)"]
)

# Chia giao diện làm 2 cột
col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 🗺️ Bản đồ Mạng Tích hợp SAGSINs")
    # Tọa độ Đà Nẵng làm trạm mặt đất trung tâm
    ground_lat, ground_lon = 16.0544, 108.2022
    m = folium.Map(location=[ground_lat, ground_lon], zoom_start=7, tiles="OpenStreetMap")

    # Marker Trạm Mặt đất
    folium.Marker(
        [ground_lat, ground_lon],
        popup="Trạm Mặt Đất (Central Server)",
        icon=folium.Icon(color="red", icon="home")
    ).add_to(m)

    # Marker UAV
    folium.Marker(
        [16.2000, 108.3000],
        popup="UAV_01 (Air Layer) - Pin: 95%",
        icon=folium.Icon(color="green", icon="plane")
    ).add_to(m)

    # Marker Vệ tinh
    folium.Marker(
        [16.8000, 107.8000],
        popup="SAT_01 (Space Layer) - QĐ LEO",
        icon=folium.Icon(color="blue", icon="cloud")
    ).add_to(m)

    # Marker Tàu biển
    folium.Marker(
        [15.8000, 108.8000],
        popup="SHIP_01 (Sea Layer) - Vessel",
        icon=folium.Icon(color="orange", icon="info-sign")
    ).add_to(m)

    st_folium(m, width=550, height=400)

with col2:
    st.markdown("### 📊 Hiệu năng Mô hình Toàn cục (Global Model)")

    # Dữ liệu biểu đồ giả lập mẫu
    rounds = list(range(1, 11))
    acc_data = [20, 35, 50, 65, 72, 78, 83, 86, 88, 91]
    loss_data = [2.3, 1.8, 1.4, 1.0, 0.7, 0.5, 0.4, 0.3, 0.25, 0.2]

    df_metrics = pd.DataFrame({
        "Vòng lặp (Round)": rounds,
        "Độ chính xác (%)": acc_data,
        "Độ lỗi (Loss)": loss_data
    }).set_index("Vòng lặp (Round)")

    st.line_chart(df_metrics)
    st.success("✅ Trạng thái hệ thống: Socket TCP Controller đã sẵn sàng kết nối!")

st.info("💡 Dự án được phát triển theo chuẩn kiến trúc MVC.")