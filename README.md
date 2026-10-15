# Federated Learning in SAGSINs

Chương trình chính mô phỏng mạng Space–Air–Ground–Sea, huấn luyện FL dự đoán độ trễ từ dữ liệu mạng trong database và so sánh chính sách chọn participant.

## Chạy ứng dụng chính

Từ thư mục gốc project, với môi trường Python đã cài `requirements.txt` và database đang chạy:

```powershell
uvicorn backend.main:app --reload
```

Mở `http://127.0.0.1:8000`, chọn **FL Training**. Tác vụ mặc định là Network delay prediction. Có thể chạy riêng từng policy hoặc so sánh Random/FedAvg, static Delay-Aware và prediction-aware trên cùng dataset. **Results** có dữ liệu thô theo client, prediction audit, metric, checkpoint inference và CSV.

`DATABASE_URL` lấy từ biến môi trường hoặc `.env`; mặc định là `mysql+pymysql://root:@localhost:3306/SAGSINs_db`. Backend tự tạo bảng còn thiếu khi khởi động, giữ nguyên dữ liệu đang có. Cần có scenario và ít nhất hai node ACTIVE để chạy thí nghiệm. Dữ liệu mạng thô được sinh từ snapshot node/link khi tạo experiment; có thể tái sử dụng dataset đã lưu.

Chức năng chính đều thuộc `backend.main:app`. `backend.network_demo` chỉ là tiện ích thử bằng database SQLite riêng.

- [Hướng dẫn dự đoán mạng và API](docs/fl-du-doan-mang-huong-dan.md)
- [Kế hoạch triển khai](docs/ke-hoach-trien-khai-fl-du-doan-mang.md)
- [Kết quả kiểm tra và giới hạn](docs/nghiem-thu-fl-du-doan-mang.md)
- [Demo MNIST tùy chọn](FL_MNIST_quickstart.md)
