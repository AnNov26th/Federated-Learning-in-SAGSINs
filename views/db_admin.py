import streamlit as st

def render_db_admin(db):
    st.title("🗄️ QUẢN TRỊ CƠ SỞ DỮ LIỆU SQLITE & XUẤT BÁO CÁO")
    st.caption("Quản lý tập trung dữ liệu CSDL `sagsins_simulation.db` và xuất báo cáo hệ thống.")

    tab1, tab2, tab3 = st.tabs([
        "📥 Data Thu Thập (collected_data)",
        "🧠 Nhật Ký FL (training_logs)",
        "📡 Lịch Sử Định Tuyến (routing_logs)"
    ])

    with tab1:
        st.dataframe(db.fetch_collected_data(), use_container_width=True)
    with tab2:
        st.dataframe(db.fetch_training_logs(), use_container_width=True)
    with tab3:
        st.dataframe(db.fetch_routing_logs(), use_container_width=True)

    st.markdown("---")
    st.subheader("📄 Trích Xuất Báo Cáo Dữ Liệu")
    c1, c2 = st.columns(2)
    with c1:
        st.button("📥 Xuất Báo Cáo Excel (.xlsx)", use_container_width=True)
    with c2:
        st.button("📄 Xuất Báo Cáo PDF", use_container_width=True)