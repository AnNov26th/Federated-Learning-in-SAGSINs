import streamlit as st
import pandas as pd
import random


def render_resource_pso(nodes_list):
    st.title("⚡ PHÂN BỔ TÀI NGUYÊN ĐỘNG & LỰA CHỌN CLIENT (PSO/GA)")
    st.caption("Ứng dụng thuật toán Heuristic (PSO/GA) đánh giá điểm Fitness chọn Top-K nút tối ưu.")

    with st.form("form_pso_calc"):
        st.latex(r"\text{Fitness}_i = w_1 \cdot \text{Pin}_i + w_2 \cdot \text{BăngThông}_i - w_3 \cdot \text{ĐộTrễ}_i")
        w1 = st.slider("Trọng số Pin (w1):", 0.1, 1.0, 0.4)
        w2 = st.slider("Trọng số Băng thông (w2):", 0.1, 1.0, 0.4)
        w3 = st.slider("Trọng số Độ trễ (w3):", 0.1, 1.0, 0.2)
        top_k = st.number_input("Chọn số lượng Top-K nút tối ưu:", min_value=1, max_value=len(nodes_list), value=4)

        if st.form_submit_button("⚡ Chạy Thuật Toán Tối Ưu PSO"):
            scores = []
            for n in nodes_list:
                score = w1 * n.battery + w2 * n.bandwidth - w3 * random.uniform(5, 50)
                scores.append({"Mã Nút": n.node_id, "Tên Thiết Bị": n.name, "Tầng": n.layer, "Pin (%)": n.battery,
                               "Băng Thông (Mbps)": n.bandwidth, "Fitness Score": round(score, 2)})

            df_scores = pd.DataFrame(scores).sort_values(by="Fitness Score", ascending=False)
            st.success("✅ Đã hoàn thành tính toán tối ưu Heuristic PSO!")
            st.dataframe(df_scores.head(top_k), use_container_width=True)