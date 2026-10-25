# Dữ liệu đầu vào và đầu ra

## Cấu trúc

```text
data/
├── input/
│   ├── global_ground_nodes/    # Nguồn địa lý, waypoint, inventory node/vệ tinh
│   └── network_benchmarks/     # Mẫu nguồn, nhãn, cấu hình/request từng benchmark
└── output/
    ├── exports/                # JSON/CSV định tuyến, báo cáo, ảnh minh chứng
    ├── network_benchmarks/     # Metric, prediction audit, checkpoint, báo cáo
    ├── global_ground_nodes/    # Kết quả kiểm chứng phủ sóng
    ├── network_demo/           # Database demo và kết quả chạy demo
    ├── training_ui_check/      # Database kiểm thử giao diện, ảnh và log demo
    ├── database_backups/       # Bản sao lưu database
    └── training_reset_backups/ # Bản sao lưu trước thao tác reset/xóa đã thực hiện
```

`input` chứa dữ liệu dùng để tạo mạng hoặc huấn luyện/đánh giá. Nhãn thật
(`target_delay_ms`) và các tập validation/test cũng là input của thí nghiệm;
không phải dự đoán đầu ra của model. MNIST, nếu tải lại, được lưu tại
`input/mnist/`; không tạo sẵn thư mục rỗng.

`output` chứa kết quả đã sinh: dự đoán, metric, trọng số/checkpoint, tuyến,
báo cáo và bản sao lưu. Một JSON kết quả có thể kèm lại request/config để audit;
giữ nguyên các bản ghi đó thay vì cắt mất thông tin tái lập.

## Đối chiếu một benchmark

Cùng tên lần chạy, ví dụ `volume_20261024T182515238765Z`:

- `input/network_benchmarks/<run>/`: `nodes.csv`, `links.csv`, `manifest.json`.
- `input/network_benchmarks/<run>/<profile_seed>/`: `source_observations.csv`,
  `small/large_request.json`, `small/large_dataset_metadata.json`.
- `output/network_benchmarks/<run>/`: bảng tổng hợp, báo cáo HTML, database demo.
- `output/network_benchmarks/<run>/<profile_seed>/`: checkpoint, experiment,
  decision audit và client outcomes.

Tạo lại báo cáo bằng:

```powershell
python -m backend.network_volume_report data/output/network_benchmarks/<run>
```

Tiện ích tự tìm input cùng tên lần chạy trong cây `data/input`.

## Database và bảo toàn dữ liệu

Database chính vẫn ở MySQL theo `DATABASE_URL`, không bị chuyển hoặc reset.
Các bảng dataset/observation/experiment/checkpoint trong MySQL không bị tách
vật lý. SQLite demo là trạng thái chạy hỗn hợp, có cả dữ liệu nguồn lẫn kết quả;
được giữ nguyên database trong `output`, không cắt bảng để tránh mất quan hệ.

Lần tổ chức ngày 25/10/2026 chỉ chuyển file, sửa đường dẫn code/tài liệu và
liên kết báo cáo. Danh sách vị trí cũ/mới và SHA-256 trước chuyển nằm trong
`output/data-reorganization.json`. Dịch vụ demo cổng 8767 được khởi động lại
với SQLite ở vị trí mới; ứng dụng MySQL chính giữ cấu hình hiện tại.

Các folder rỗng đã được xóa; không có file 0 byte trong dữ liệu lúc kiểm tra.
Không xóa bản sao lưu, checkpoint hoặc dữ liệu có nội dung. Các báo cáo lịch sử
vẫn có thể nhắc đường dẫn cũ trong nội dung audit; dùng danh sách chuyển file để
tra vị trí mới.
