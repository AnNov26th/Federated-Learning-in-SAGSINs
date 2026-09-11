import streamlit as st
import folium
from streamlit_folium import st_folium
from models.routing import SAGSINRoutingEngine


def render_routing(servers_dict, nodes_list, nodes_dict, db, create_base_map):
    st.title("📡 ĐỊNH TUYẾN THÔNG TIN NHANH NHẤT (DIJKSTRA LATENCY)")
    st.caption("Tự động tính toán tổng độ trễ lan truyền vô tuyến và độ trễ truyền tải để chọn tuyến đường tối ưu.")

    with st.form("form_routing_calc"):
        r_col1, r_col2 = st.columns(2)
        with r_col1:
            src_node_key = st.selectbox("Nút nguồn gửi thông tin:", list(nodes_dict.keys()))
        with r_col2:
            target_server_key = st.selectbox("Trạm mặt đất đích:", list(servers_dict.keys()))

        data_size = st.slider("Kích thước gói tin truyền tải (MB):", 0.5, 20.0, 2.5, 0.5)

        if st.form_submit_button("🚀 Tính Toán Tuyến Nhanh Nhất (Dijkstra)"):
            all_entities = []
            for s_id, s in servers_dict.items():
                all_entities.append({'id': s_id, 'name': s.name, 'lat': s.lat, 'lon': s.lon, 'layer': 'GroundServer',
                                     'bandwidth': 1000.0})
            for n in nodes_list:
                all_entities.append({'id': n.node_id, 'name': n.name, 'lat': n.lat, 'lon': n.lon, 'layer': n.layer,
                                     'bandwidth': n.bandwidth, 'orbit_altitude': getattr(n, 'orbit_altitude', 0)})

            src_id = nodes_dict[src_node_key].node_id
            path, total_latency, bw = SAGSINRoutingEngine.find_optimal_route(all_entities, src_id, target_server_key)

            if path and len(path) > 1:
                entity_lookup = {e['id']: e for e in all_entities}
                path_names = [entity_lookup[h]['name'] for h in path]
                path_str = " ➔ ".join(path_names)

                st.success(f"🚀 **TUYẾN ĐƯỜNG TỐI ƯU:** {path_str}")
                st.info(f"⏱️ **Tổng độ trễ:** {total_latency:.2f} ms | ⚡ **Băng thông cổ chai:** {bw} Mbps")
                db.insert_routing_log(nodes_dict[src_node_key].name, servers_dict[target_server_key].name, path_str,
                                      total_latency, bw)

                m_route = create_base_map()
                path_coords = [[entity_lookup[h]['lat'], entity_lookup[h]['lon']] for h in path]
                for h in path:
                    e = entity_lookup[h]
                    folium.Marker([e['lat'], e['lon']], popup=f"Hop: {e['name']}").add_to(m_route)
                folium.PolyLine(path_coords, color="red", weight=5, opacity=0.9).add_to(m_route)
                st_folium(m_route, use_container_width=True, height=450)

    st.markdown("### 🗄️ Lịch Sử Định Tuyến Trong CSDL")
    st.dataframe(db.fetch_routing_logs(), use_container_width=True)