import streamlit as st


def render_data_collect(nodes_dict, db):
    st.title("📥 THU THẬP & TIỀN XỬ LÝ DỮ LIỆU CẢM BIẾN BIÊN")
    st.caption("Khởi tạo các bài toán thu thập dữ liệu thô phân tán tại các thiết bị biên SAGSINs.")

    with st.form("form_data_collect"):
        st.subheader("📝 Khai Báo Dữ Liệu Thu Thập Mới")
        selected_node_key = st.selectbox("Chọn thiết bị thu thập:", list(nodes_dict.keys()))
        data_types_map = {
            "Air": "Ảnh Hồng Ngoại UAV / Giám Sát Cháy Rừng",
            "Space": "Ảnh Viễn Thám Vệ Tinh Radar Đa Phổ",
            "Sea": "Tín Hiệu Sóng Âm Sonar Lòng Biển",
            "Ground": "Video Camera Giao Thông Đô Thị"
        }
        node_obj = nodes_dict[selected_node_key]
        dtype = st.text_input("Loại dữ liệu thô:", value=data_types_map.get(node_obj.layer, "Dữ liệu Cảm Biến"))
        samples = st.number_input("Số lượng mẫu thu thập (samples):", min_value=50, max_value=5000, value=500, step=100)
        desc = st.text_area("Mô tả nhiệm vụ:", value=f"Nhiệm vụ quét dữ liệu môi trường khu vực {node_obj.name}")

        if st.form_submit_button("📥 Thu Nhập & Ghi Vào CSDL SQLite"):
            db.insert_collected_data(node_obj.node_id, node_obj.name, node_obj.layer, dtype, samples, desc)
            st.success(f"✅ Đã lưu thành công {samples} mẫu dữ liệu từ **{node_obj.name}** vào CSDL!")

    st.markdown("### 🗄️ Lịch Sử Thu Thập Trong CSDL SQLite")
    st.dataframe(db.fetch_collected_data(), use_container_width=True)