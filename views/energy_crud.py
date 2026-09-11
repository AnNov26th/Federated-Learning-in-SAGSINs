import streamlit as st
import random
from models import UAV, Satellite, Ship, Vehicle


def render_energy_crud(servers_dict, nodes_dict, db):
    st.title("🔋 GIÁM SÁT NĂNG LƯỢNG, CỨU HỘ & QUẢN LÝ NODE")
    st.caption(
        "Giám sát dung lượng pin, phát tín hiệu triệu tập trạm sạc tự động, cứu hộ năng lượng khẩn cấp và quản trị nút.")

    nodes_list = st.session_state.nodes_list
    low_bat_nodes = [n for n in nodes_list if n.battery <= 20.0]
    critical_nodes = [n for n in nodes_list if n.battery <= 10.0]

    e1, e2, e3 = st.columns(3)
    e1.metric("🔋 Nút Bình Thường (>20%)", len(nodes_list) - len(low_bat_nodes))
    e2.metric("⚠️ Nút Cần Triệu Tập (<=20%)", len(low_bat_nodes), delta="-Cảnh báo", delta_color="inverse")
    e3.metric("🚨 Nút Cạn Kiệt Khẩn Cấp (<=10%)", len(critical_nodes), delta="-Nguy cấp", delta_color="inverse")

    st.markdown("---")
    act1, act2, act3 = st.columns(3)
    with act1:
        if st.button("🚀 Triệu Tập Về Trạm Sạc (Auto Recall)", use_container_width=True):
            if low_bat_nodes:
                st.warning(f"⚠️ Đã phát lệnh triệu tập {len(low_bat_nodes)} nút về Trạm sạc gần nhất!")
            else:
                st.success("✅ Tất cả các nút đều đủ pin (>20%)!")

    with act2:
        if st.button("🚁 Điều Động Xe/UAV Cứu Hộ Năng Lượng", use_container_width=True):
            if critical_nodes:
                st.error(
                    f"🚨 Đã điều động thiết bị cứu hộ mang pin dự phòng đến sạc cho {len(critical_nodes)} nút nguy cấp!")
            else:
                st.info("ℹ️ Không có nút nào cạn kiệt khẩn cấp (<=10%).")

    with act3:
        if st.button("⚡ Sạc Đầy 100% Pin Tất Cả Các Nút", use_container_width=True):
            for n in nodes_list:
                n.battery = 100.0
            st.success("⚡ Đã sạc đầy pin 100% cho toàn bộ thiết bị!")

    st.markdown("---")
    st.subheader("✏️ Quản Trị Node (CRUD)")
    tab_add, tab_edit, tab_del = st.tabs(["➕ Thêm Node Mới", "✏️ Sửa Thông Số Node", "🗑️ Xóa Node"])

    with tab_add:
        with st.form("form_node_add"):
            c1, c2 = st.columns(2)
            with c1:
                new_id = st.text_input("Mã Nút (ID):", value=f"NODE_{random.randint(100, 999)}")
                new_name = st.text_input("Tên Thiết Bị:", value="Drone Giám Sát Mới")
                new_layer = st.selectbox("Tầng Mạng Vật Lý:", ["Air", "Space", "Sea", "Ground"])
            with c2:
                new_lat = st.number_input("Vĩ độ (Lat):", value=16.0500, format="%.4f")
                new_lon = st.number_input("Kinh độ (Lon):", value=108.2000, format="%.4f")
                new_bat = st.slider("Dung Lượng Pin (%):", 10.0, 100.0, 90.0)
                new_bw = st.number_input("Băng Thông (Mbps):", value=50.0)

            if st.form_submit_button("➕ Thêm Thiết Bị Vô Mạng"):
                if new_layer == "Air":
                    new_obj = UAV(node_id=new_id, name=new_name, lat=new_lat, lon=new_lon, battery=new_bat,
                                  bandwidth=new_bw)
                elif new_layer == "Space":
                    new_obj = Satellite(node_id=new_id, name=new_name, lat=new_lat, lon=new_lon, battery=new_bat,
                                        bandwidth=new_bw, orbit_altitude=600)
                elif new_layer == "Sea":
                    new_obj = Ship(node_id=new_id, name=new_name, lat=new_lat, lon=new_lon, battery=new_bat,
                                   bandwidth=new_bw)
                else:
                    new_obj = Vehicle(node_id=new_id, name=new_name, lat=new_lat, lon=new_lon, battery=new_bat,
                                      bandwidth=new_bw)

                st.session_state.nodes_list.append(new_obj)
                st.success(f"✅ Đã thêm thành công {new_name} ({new_id})!")
                st.rerun()

    with tab_edit:
        with st.form("form_node_edit"):
            edit_key = st.selectbox("Chọn nút cần sửa:", list(nodes_dict.keys()))
            target_n = nodes_dict[edit_key]
            e_lat = st.number_input("Sửa Vĩ độ:", value=float(target_n.lat), format="%.4f")
            e_lon = st.number_input("Sửa Kinh độ:", value=float(target_n.lon), format="%.4f")
            e_bat = st.slider("Sửa Pin (%):", 0.0, 100.0, float(target_n.battery))
            e_bw = st.number_input("Sửa Băng Thông (Mbps):", value=float(target_n.bandwidth))

            if st.form_submit_button("💾 Lưu Thay Đổi"):
                target_n.lat, target_n.lon, target_n.battery, target_n.bandwidth = e_lat, e_lon, e_bat, e_bw
                st.success(f"✅ Cập nhật thành công cho {target_n.name}!")
                st.rerun()

    with tab_del:
        with st.form("form_node_del"):
            del_key = st.selectbox("Chọn nút muốn xóa khỏi mạng:", list(nodes_dict.keys()))
            if st.form_submit_button("🗑️ Xác Nhận Xóa Node"):
                del_obj = nodes_dict[del_key]
                st.session_state.nodes_list = [n for n in st.session_state.nodes_list if n.node_id != del_obj.node_id]
                st.success(f"✅ Đã xóa nút {del_obj.name}!")
                st.rerun()