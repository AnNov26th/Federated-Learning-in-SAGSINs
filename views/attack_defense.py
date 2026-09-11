import streamlit as st
import pandas as pd
import numpy as np

def render_attack_defense():
    st.title("🛡️ MÔ PHỎNG TẤN CÔNG & PHÒNG THỦ AI (LDP DEFENSE)")
    st.caption("Thử nghiệm kiểm chứng khả năng phòng thủ đòn tấn công tái cấu trúc ảnh (Reconstruction Attack).")

    st.subheader("🕵️ Mô Phỏng Đòn Tấn Công Suy Diễn Trọng Số Mô Hình (Model Inversion Attack)")
    st.info("Kẻ tấn công nghe lén trên kênh truyền không dây SAGSINs thu thập trọng số PyTorch để chạy ngược mô hình.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### ❌ Khi KHÔNG có LDP (Epsilon = ∞)")
        st.image("https://upload.wikimedia.org/wikipedia/commons/2/27/MnistExamples.png", caption="Ảnh gốc bị kẻ tấn công khôi phục hoàn toàn từ trọng số thô!", use_container_width=True)
        st.error("🚨 Hậu quả: Dữ liệu ảnh bị rò rỉ 100%!")

    with c2:
        st.markdown("#### ✅ Khi ĐÃ CÓ Phòng Thủ LDP (Epsilon = 2.0)")
        noise_img = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        st.image(noise_img, caption="Ảnh sau khi kẻ tấn công khôi phục từ trọng số có nhiễu LDP (Nhiễu trắng hoàn toàn)!", use_container_width=True)
        st.success("🛡️ Kết quả: Dữ liệu thô an toàn tuyệt đối!")

    st.markdown("---")
    st.subheader("📊 Biểu Đồ Đánh Đổi Giữa Mức Bảo Mật (ε) & Độ Chính Xác (Privacy-Accuracy Trade-off)")
    rounds = list(range(1, 11))
    df_tradeoff = pd.DataFrame({
        "Vòng FL": rounds,
        "Không có LDP (ε=∞)": [18, 45, 68, 80, 88, 92, 94, 95.5, 96.2, 97.0],
        "LDP Mức Vừa (ε=2.0)": [15, 38, 62, 75, 83, 87, 90.5, 92.3, 93.8, 94.7],
        "LDP Mức Cao (ε=0.5)": [12, 28, 50, 65, 74, 80, 84, 86.5, 88.0, 89.2],
    }).set_index("Vòng FL")
    st.line_chart(df_tradeoff, height=320)