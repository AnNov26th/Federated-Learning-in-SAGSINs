import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd

def render_gis_map(servers_dict, nodes_list, create_base_map):
    st.title("🗺️ GIÁM SÁT MẠNG THỜI GIAN THỰC & BẢN ĐỒ GIS LIVE")
    st.caption("Giám sát vị trí thực tế của Vệ tinh, UAV, Tàu biển, Xe thông minh và Trạm mặt đất.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🏠 Trạm Mặt Đất", len(servers_dict))
    c2.metric("🛸 Nút Biên Hoạt Động", len(nodes_list))
    avg_bat = sum(n.battery for n in nodes_list) / len(nodes_list) if nodes_list else 0
    c3.metric("🔋 Pin TB Hệ Thống", f"{avg_bat:.1f}%")
    avg_bw = sum(n.bandwidth for n in nodes_list) / len(nodes_list) if nodes_list else 0
    c4.metric("📡 Băng Thông TB", f"{avg_bw:.1f} Mbps")

    m = create_base_map()
    color_map = {"Air": "green", "Space": "blue", "Sea": "orange", "Ground": "purple"}
    icon_map = {"Air": "plane", "Space": "cloud", "Sea": "info-sign", "Ground": "user"}

    for s_id, server in servers_dict.items():
        folium.Marker(
            [server.lat, server.lon],
            popup=f"<b>🏠 {server.name} ({server.station_id})</b><br>Server Trung Tâm",
            icon=folium.Icon(color="red", icon="home")
        ).add_to(m)

    for node in nodes_list:
        popup_html = f"<b>{node.name} ({node.node_id})</b><br>Tầng: {node.layer}<br>Pin: {node.battery}% | BW: {node.bandwidth} Mbps"
        folium.Marker(
            [node.lat, node.lon],
            popup=popup_html,
            icon=folium.Icon(color=color_map.get(node.layer, "gray"), icon=icon_map.get(node.layer, "info-sign"))
        ).add_to(m)

    folium.LayerControl(position="topright").add_to(m)
    st_folium(m, use_container_width=True, height=500)

    st.markdown("### 📋 Bảng Chi Tiết Trạng Thái Nút Biên")
    df_nodes = pd.DataFrame([n.to_dict() for n in nodes_list])
    st.dataframe(df_nodes, use_container_width=True)