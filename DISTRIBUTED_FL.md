# Hợp nhất lõi Second vào dự án gốc

Ngày 26/10/2026, Asia/Saigon. Giữ giao diện A; thay bộ thực thi phía sau bằng các
khối tốt hơn của B, không nhúng một ứng dụng nghiên cứu thứ hai.

## Công nghệ và luồng chính

| Thành phần | Công nghệ được dùng |
|---|---|
| Giao diện, địa cầu, inventory, scenario | A, giữ cấu trúc/màu sắc/điều hướng |
| API, lịch sử experiment và ORM | FastAPI + SQLAlchemy của A |
| FL worker và truyền model | multiprocessing + HTTP, xác thực, kiểm tra phiên bản từ B |
| Dữ liệu huấn luyện mới | MySQL schema/account riêng cho từng client, cách tổ chức của B |
| Predictor | Trend 4 tham số hoặc MLP residual, codec JSON/float32 lossless từ B |
| Topology và hình học | Snapshot toàn scenario từ A, kiểm tra ACTIVE/tầm nhìn/khoảng cách |
| Cấp phát | Equal/Demand/Minimax/Deadline của B, thêm ràng buộc node/access cho flow A |
| Theo dõi | API/SSE/Experiments/Results cũ của A, thêm cancel/resume và baseline/replay |

`POST /api/fl/experiments` vẫn trả ID số trong bảng `experiments` của A. Với
network-delay mới, API chỉ tạo metadata/snapshot; client tự tạo và đọc dữ liệu
local. Coordinator phát global model, nhận update, kiểm tra client/round/tensor
và tổng hợp FedAvg. Mỗi vòng chấm validation; test chỉ được chấm sau training.
Kết quả và checkpoint được ánh xạ về `fl_rounds`, `fl_client_rounds`, `metrics`,
`network_round_evaluations` để các trang cũ tiếp tục hoạt động.

Predictive chọn theo chi phí tuyến dự đoán đến ground đích; DelayAware dùng
telemetry hiện tại; FedAvg chọn random. Đây là proxy của simulator, không gọi
độ trễ ứng dụng là thời gian upload model qua HTTP. Local-only dùng tổng epochs
mà từng client thực sự đóng góp. Centralized là công cụ offline có quyền đọc
local data riêng, không nhập vào giao thức coordinator.

## Quy mô toàn cầu và worker

Nghiệm thu dùng scenario #6, **178 node, 460 link ACTIVE, 178 client trong pool**,
chọn 24 client/vòng. Không thay bằng topology 12 node của B. Tọa độ, inventory,
liên kết và các scenario cũ được giữ. Tên scenario lịch sử có số 106 vẫn giữ để
bảo toàn tham chiếu; số node thực lấy từ snapshot/database.

`max_workers=4` tạo bốn tiến trình thực thi cho toàn bộ pool. Mỗi tiến trình host
một nhóm client logic; từng client có DB account, dữ liệu, khóa và cache round
riêng. Khóa dùng chung trong mỗi tiến trình tuần tự hóa PyTorch để tránh tranh
chấp RNG giữa các client. Đây không phải 178 máy hoặc 178 OS sandbox độc lập.
Số node/client trong mô phỏng không bị cắt theo số tiến trình.

178 node là inventory mô phỏng có phân bố toàn cầu, không đại diện mọi hạ tầng
viễn thông ngoài thực địa. Không tự thêm node/link chỉ để tăng con số hoặc ép
mọi tọa độ đều có tuyến. Snapshot không phải mô phỏng quỹ đạo liên tục.

## Database và tương thích

- DB gốc tiếp tục giữ node/link/scenario và toàn bộ lịch sử experiment.
- Các bảng mới `network_clocks` và `network_allocation_settings` được tạo bổ sung,
  không DROP/reset DB. Chúng lưu thời gian và policy cấp phát cho từng scenario.
- Metadata dataset mới ghi runtime `federated-http-v3`, feature `application-link-v2`,
  target `next_tick_reference_payload_delay_ms`, snapshot, fingerprint và số mẫu
  thực tế do client báo. Không ghi raw rows mới vào `network_observations`.
- API observations từ coordinator từ chối dataset local mới. Metadata, metric,
  model và audit vẫn xuất được. Dataset/checkpoint lịch sử không bị đổi target.
- `.secrets/distributed-fl.json`: bootstrap account client theo node (tên schema
  chứa hash để hỗ trợ ID toàn cầu). Runtime cấp bổ sung account còn thiếu khi cần.
- `.secrets/main-database.json`: account vận hành backend chính, chỉ có quyền
  trong DB gốc. Sau setup cần restart backend để dùng account này.
- Provisioner lấy cấu hình từ `DATABASE_URL`/`MYSQL_ADMIN_USER`/`MYSQL_ADMIN_PASSWORD`;
  quyền quản trị chỉ phục vụ cấp account/schema. File bí mật bị bỏ qua bởi Git.
- Artifacts của experiment gốc: `data/output/distributed_fl/experiments/<runtime_id>/`.
  ID số của experiment chứa mapping này trong config, không có lịch sử UI thứ hai.
- Các artifact `runs/` của lần tích hợp thử trước được giữ, không dùng làm runtime
  chính. Không sao chép database, credential hoặc kết quả từ thư mục Second.

Checkpoint mới được chọn ngay trong Simulation thông qua adapter phiên bản;
checkpoint cũ vẫn có loader cũ. Ingress dùng telemetry hiện tại; model backbone
chỉ chấm các hop. Feature link dùng cùng bộ lịch sử/queue như client training.
Payload/lưu lượng khác điều kiện huấn luyện vẫn cần kiểm chứng, không bảo đảm
model tổng quát cho mọi ứng dụng.

## Flow trên địa cầu

Sự kiện mới có flow hữu hạn, lượng dữ liệu còn lại, tốc độ được cấp, deadline,
lịch sử và trạng thái hoàn tất/hết hạn. Clock chạy ở backend; nhiều tab không
làm clock chạy nhanh hơn. Allocator kiểm tra tổng rate trên từng link, node và
access trước khi thực hiện service. Hoàn tất/hết hạn giải phóng tài nguyên.
Policy là cấu hình chung theo scenario; lựa chọn của sự kiện/checkpoint mới
cập nhật policy cho các flow đang hoạt động của scenario đó.

Routing giữ điều kiện truy cập/geometry của A. Xét lại tuyến theo chu kỳ, ngưỡng
cải thiện 15% và pause khi chuyển tuyến. No-path chờ thử lại có thời hạn. Các
luồng điều động thử nghiệm và lịch sử cũ vẫn giữ hành vi tương thích; không dùng
vệ tinh như phương tiện tự bay đến sự kiện để chứng nhận phủ sóng.

Results hiển thị tám đối chứng với simulator riêng cho từng policy, completion,
delivery, throughput, fairness, kiểm tra capacity và replay từ audit. Cần đọc
completion cùng delivery. Minimax tối ưu cửa sổ tĩnh/tuyến cố định; deadline là
heuristic. Không suy ra tối ưu toàn cục hoặc bảo đảm QoS ngoài thực địa.

## Chạy và kiểm tra

```powershell
# Máy mới; bật MySQL trước:
.\setup-distributed.ps1
# Một server duy nhất, không reload khi chạy thí nghiệm:
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# Bộ kiểm thử:
.\.venv\Scripts\python.exe -m unittest discover -s tests
# Nghiệm thu qua API gốc, tự chọn scenario lớn nhất:
.\.venv\Scripts\python.exe -m sagsin.smoke --url http://127.0.0.1:8000 --resume
# Benchmark cùng API và pool toàn cầu; --clients là số được chọn mỗi vòng:
.\.venv\Scripts\python.exe -m sagsin.benchmark --url http://127.0.0.1:8000 --seeds 11 42 71 101 137 --rounds 5 --clients 24
# Đối chứng codec/model ghép cặp:
.\.venv\Scripts\python.exe -m sagsin.upgrade_benchmark --url http://127.0.0.1:8000 --compare-upgrades
# Centralized offline của một experiment đã hoàn tất:
.\.venv\Scripts\python.exe -m sagsin.offline data/output/distributed_fl/experiments/<runtime_id>
```

Chỉ dùng loopback. Chưa có TLS/DP/secure aggregation, triển khai LAN nhiều máy,
RF hoặc packet-level. MySQL phân quyền không chống được quản trị viên hoặc
process có quyền đọc credential trên cùng máy. Body byte chỉ là HTTP JSON body,
không gồm header/TCP/TLS hoặc IPC bootstrap. Không gọi đây là privacy hình thức.

## Minh chứng

146/146 kiểm thử đã PASS: core B, API/topology/flow hợp nhất và kiểm thử cũ của A.
Các fixture kiểm chứng runtime cũ đặt `runtime=legacy` rõ ràng; test mới kiểm
chứng mặc định HTTP, giữ topology scenario, không tập trung raw data, dùng chung
capacity và ngừng cấp tốc độ khi link INACTIVE.

Báo cáo nghiệm thu mới lưu ở `data/output/distributed_fl/acceptance/unified.json`.
Các lượt đã kiểm chứng trên A: experiment #7 (178 client, 2 vòng), #8 (hủy sau
vòng 1 rồi tiếp tục đủ 8 vòng); audit khớp từng tensor và account backend chính
bị từ chối SELECT DB client. Event #48 dùng checkpoint #7, truyền đủ 0,5 Mbit,
hoàn tất và giải phóng băng thông qua clock/allocator mới. Lượt #9 lỗi startup
worker được giữ lại; không xóa kết quả thất bại. Log startup đã được bổ sung.

Benchmark nhiều seed toàn ma trận chưa chạy trong lượt hợp nhất này. Các kết quả
nghiệm thu xác nhận hệ thống hoạt động, chưa chứng minh FL luôn thắng baseline.

Nghiệm thu cuối trên server chính: {"experiment_id": 10, "pool": 178, "nodes": 178, "links": 460, "completed_rounds": 2, "resume": {"experiment_id": 11, "retained_rounds": 1, "completed_rounds": 8}}. Ảnh giao diện gốc: `data/output/distributed_fl/unified-results.png`. Startup worker có retry giới hạn một lần và giữ log; không xóa lượt lỗi.
