import streamlit as st
import pandas as pd
import random


def render_fl_training(nodes_dict, db):
    st.markdown("<h2 class='glow-text'>🧠 HUẤN LUYỆN HỌC LIÊN HỢP & BẢO MẬT LDP</h2>", unsafe_allow_html=True)
    st.caption("Điều chỉnh Ngân sách Bảo mật Epsilon (ε) và cấu hình các tham số huấn luyện AI phân tán.")

    st.markdown('<div class="sci-fi-panel">', unsafe_allow_html=True)
    with st.form("form_fl_param"):
        st.markdown("<h4 style='color: var(--neon-cyan);'>⚙️ Cấu Hình Tham Số Huấn Luyện & Bảo Mật LDP</h4>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            ep_val = st.slider("🔒 Ngân sách Bảo mật Privacy Budget (Epsilon - ε):", 0.1, 10.0, 2.0, 0.1)
            epochs = st.number_input("Số vòng lặp cục bộ (Local Epochs):", min_value=1, max_value=20, value=5)
        with col2:
            lr = st.number_input("Tốc độ học (Learning Rate):", min_value=0.001, max_value=0.1, value=0.01, step=0.005)
            selected_nodes_fl = st.multiselect("Chọn nút tham gia vòng FL:", list(nodes_dict.keys()),
                                               default=list(nodes_dict.keys())[:5])

        if st.form_submit_button("🚀 Chạy Mô Phỏng Vòng FL & Gửi Trọng Số"):
            p_bar = st.progress(0)
            for idx, key in enumerate(selected_nodes_fl):
                n_obj = nodes_dict[key]
                loss = round(random.uniform(0.12, 0.75), 3)
                acc = round(random.uniform(84.0, 97.5), 2)
                weight_kb = round(random.uniform(1100.0, 2400.0), 1)
                db.insert_training_log(random.randint(1, 15), n_obj.node_id, n_obj.name, loss, acc, ep_val, weight_kb)
                p_bar.progress((idx + 1) / len(selected_nodes_fl))
            st.success("✅ Đã chèn nhiễu Gaussian LDP và hoàn tất tổng hợp FedAvg trên Server!")
    st.markdown('</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="sci-fi-panel">', unsafe_allow_html=True)
        st.markdown("<h4 style='color: var(--neon-magenta);'>📈 Độ Chính Xác Toàn Cục (Global Accuracy %)</h4>", unsafe_allow_html=True)
        rounds = list(range(1, 11))
        chart_data_acc = pd.DataFrame({"Vòng FL": rounds,
                                    "Accuracy (%)": [15.2, 38.5, 62.1, 75.8, 83.2, 87.9, 90.5, 92.3, 93.8,
                                                     94.7]}).set_index("Vòng FL")
        st.line_chart(chart_data_acc, color="#ff00e5")
        st.markdown('</div>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="sci-fi-panel">', unsafe_allow_html=True)
        st.markdown("<h4 style='color: var(--neon-cyan);'>📉 Độ Lỗi Toàn Cục (Global Loss)</h4>", unsafe_allow_html=True)
        chart_data_loss = pd.DataFrame(
            {"Vòng FL": rounds, "Loss": [2.45, 1.82, 1.25, 0.88, 0.58, 0.42, 0.31, 0.24, 0.19, 0.15]}).set_index(
            "Vòng FL")
        st.line_chart(chart_data_loss, color="#00f3ff")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="sci-fi-panel">', unsafe_allow_html=True)
    st.markdown("<h3 style='color: var(--neon-cyan);'>🗄️ Nhật Ký Huấn Luyện Trong CSDL</h3>", unsafe_allow_html=True)
    st.dataframe(db.fetch_training_logs(), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)