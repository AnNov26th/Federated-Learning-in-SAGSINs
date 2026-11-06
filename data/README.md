# Dữ liệu để xem và trình bày

Mở các file ngay trong thư mục này; không cần tìm trong thư mục con.
Tất cả thuộc experiment #24, dataset #13, seed 42.

| File | Mở khi cần xem |
|---|---|
| [nodes.json](nodes.json) | 178 node trong topology snapshot của thí nghiệm |
| [links.json](links.json) | Các link, băng thông, độ trễ lan truyền và khoảng cách |
| [observations.json](observations.json) | Toàn bộ 26.878 mẫu đầu vào/nhãn; trường split chỉ rõ train, validation, test |
| [training.json](training.json) | Cấu hình, 10 vòng huấn luyện, client tham gia và checkpoint |
| [predictions.json](predictions.json) | 5.162 mẫu test, dự đoán trước/sau học và sai số |
| [routing.json](routing.json) | Chỉ số chính sách, cặp flow đối chứng/FL và lịch sử chọn tuyến |
| [metadata.json](metadata.json) | Nguồn dữ liệu, ý nghĩa cột, đơn vị, số liệu kiểm tra và hash các file |

## Cách đọc

- nodes.json, links.json, observations.json là mảng bản ghi.
- training.json có config, split_counts, round_metrics, client_rounds, checkpoint.
- predictions.json có metrics và test_predictions.
- routing.json có policy_metrics, paired_flows, route_decisions, flows.
- Mỗi mẫu observations chứa split: train (16.554), validation (5.162), test (5.162).
  Không lưu thêm ba bản sao riêng để tránh trùng dữ liệu.
- observed_delay_ms là độ trễ tại t, target_ms là nhãn tại t+1. Hai cột này không
  phải trước/sau tối ưu. Muốn so sánh trước/sau học, mở predictions.json.
- Dữ liệu là mô phỏng synthetic; không phải phép đo từ vệ tinh/UAV/tàu thực.
- Sai số dự đoán giảm không tự chứng minh QoS/throughput tốt hơn; đọc routing.json.

## Dữ liệu chạy ứng dụng

Checkpoint, inventory nguồn, kết quả đầy đủ và backup được giữ riêng trong
storage/ ở thư mục gốc dự án. Backend vẫn dùng MySQL và storage/output/distributed_fl.
Các JSON tại data/ là bản minh chứng cố định, không tự đổi theo mỗi lần chạy mô phỏng.
Không cần mở storage/ khi chỉ trình bày dữ liệu với giảng viên.
