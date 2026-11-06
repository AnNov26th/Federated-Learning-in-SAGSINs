# Bàn giao và nghiệm thu — 31/10/2026

Đây là hướng dẫn hiện hành. Tài liệu ngày 23–27/10 mô tả lịch sử và nghiệm thu
tại thời điểm đó; không dùng các con số lịch sử làm trạng thái server hiện tại.
Kết quả đã chạy: [ACCEPTANCE_RESULTS.md](ACCEPTANCE_RESULTS.md).
Kiểm tra cuối đạt 181 Python tests, 3 JavaScript tests và startup SQLite mới.

## 1. Cài đặt và kiểm tra từ môi trường mới

Giải nén source, mở PowerShell tại thư mục gốc. Môi trường đã kiểm tra là Windows,
Python 3.14.2. `requirements-lock.txt` chốt các phiên bản môi trường nghiệm thu;
máy khác nền tảng có thể dùng phạm vi trong `requirements.txt` và chạy lại kiểm tra.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m sagsin.release_check
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/service-path.test.mjs
```

`release_check` khởi động app thật bằng TestClient/lifespan với SQLite tạm mới:
kiểm tra migration, health, 178 node, các tài nguyên giao diện và state dịch vụ.
Nó không kết nối MySQL vận hành, không huấn luyện và không reset dữ liệu.
Đây là xác nhận startup/API; không thay thế kiểm tra trình duyệt hoặc MySQL.

## 2. Tái lập benchmark offline, không cần MySQL

Inventory và năm checkpoint đã đóng băng nằm trong `storage/input/acceptance_20261031/`.
Gói này có config/topology/model, không có raw observations hoặc credential.
Không cần sao chép database của người làm trước.

```powershell
.\.venv\Scripts\python.exe -m sagsin.acceptance_matrix --package storage/input/acceptance_20261031 --output storage/output/replay-local --ticks 30
```

Output phải là thư mục mới để giữ bằng chứng các lượt cũ. Báo cáo HTML/CSV/JSON,
workload, khoảng tin cậy và hash đầu vào/mã nguồn được tạo cùng thư mục.
Chỉ coi một lượt hoàn tất nếu `methodology.json` có `complete=true`.
Lượt bị dừng trong `storage/output/acceptance_20261031/` giữ `complete=false` và
không được tính là kết quả. Kết quả cuối nằm trong
`storage/output/acceptance_20261031_final/report.html`.

Ma trận: normal (3 cặp), concurrent_congested (12 cặp, 25% residual capacity),
mixed_outage (6 cặp, 50% capacity), gaming_outage (6 cặp), smartphone_access
(3 cặp đặt ngay tọa độ GROUND, không chứng minh phủ sóng mọi vị trí).
Mỗi tình huống chạy 5 seed, 30 tick, so sánh static/current/FL trên cùng workload.
Ba chính sách có tổng 4.500 trường hợp cặp-client/tick mỗi chính sách trên ma trận.
Mọi checkpoint được huấn luyện normal: mixed/congested là kiểm tra dịch chuyển
phân phối, chưa phải FL đã huấn luyện thích nghi cho các profile đó.

Chọn tuyến tại t, chấm tại t+1, model đóng băng. Hai chiều chia sẻ dung lượng
link/node/access. Trừ 0,1 giây khi thiết lập hoặc chấp nhận chuyển tuyến.
Khoảng giữa cửa sổ outage bỏ một tập contact xác định bằng seed (~25%);
không đọc trạng thái t+1 để quyết định tại t. Capacity scale mô phỏng phần dung
lượng bị đặt trước, không thay nhãn trễ synthetic hoặc retrain model.

Delivery là tổng Mbit thực truyền / tổng nhu cầu hai chiều trên mọi trường hợp.
QoS cần cả hai chiều đủ tốc độ sau pause và đạt ngân sách trễ của dịch vụ.
Trễ trung bình là giá trị lớn hơn giữa hai chiều, chỉ trên trường hợp có tuyến;
luôn đọc cùng availability. Khoảng tin cậy bootstrap 95% lấy mẫu theo seed,
5.000 lượt, không coi tick/link là mẫu độc lập. Delta = FL − baseline.
Năm seed, cửa sổ 30 giây và nhiều so sánh chỉ hỗ trợ kết luận thăm dò.

Phiên live và benchmark dùng fluid allocator; chưa phải packet-level/RF hoặc
media thật. Chi phí truyền model nằm trong báo cáo training kèm input package,
chỉ tính JSON body, không phải toàn bộ TCP/TLS. Các số QoS/delivery mới có pause
và access nên không so trực tiếp với benchmark lịch sử thiếu hai yếu tố này.

## 3. Demo ứng dụng với MySQL

Máy mới cần MySQL/MariaDB đang hoạt động và database riêng đã tồn tại.
Đặt `DATABASE_URL` bằng biến môi trường hoặc `.env` cục bộ, rồi chạy:

```powershell
.\setup-distributed.ps1 -SkipInstall
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Chỉ một backend/worker. Không dùng `--reload` khi huấn luyện dài. Setup cấp
schema/account client cục bộ; cần tài khoản quản trị DB để provision, xem
`DISTRIBUTED_FL.md`. Không đưa `.env` và `.secrets` vào Git hoặc gói bàn giao.

Kịch bản trình diễn:

1. Mở localhost:8000; kiểm tra `/api/health` có `database_ready=true`.
2. Network: chọn scenario toàn cầu; kiểm tra inventory và trạng thái link.
3. FL Training: network_delay, pool all, 24 client/vòng, 5 vòng, 160 mẫu,
   seed 42, normal, Trend/packed. Chạy lượt mới chỉ khi cần demo training;
   bộ tái lập offline đã có model nên không bắt buộc huấn luyện lại.
4. Experiments/Results: xem progress, checkpoint, baseline và chi phí truyền.
5. Simulation: đặt hai network_gateway gần GROUND ở hai vùng, Video Call;
   nhận cuộc gọi, chạy clock, quan sát rate hai chiều và route audit.
6. Kết thúc phiên để trả bandwidth; thử Emergency và xác nhận ACK.
7. Mở báo cáo ma trận offline, trình bày cả tình huống FL không cải thiện QoS.

Checkpoint offline không tự nhập vào DB/UI; máy mới cần experiment riêng để
demo tuyến FL live. Không tuyên bố LAN nhiều máy, TLS, DP/secure aggregation,
SGP4 hoặc bảo đảm QoS thực địa. Không dùng ảnh nghiệm thu cũ làm minh chứng live.

## 4. Tạo gói source và minh chứng

```powershell
.\.venv\Scripts\python.exe -m sagsin.release_bundle --output storage/output/releases/sagsin-20261031.zip
```

ZIP chứa source, tests, inventory, checkpoint offline, báo cáo ma trận và tài
liệu; có SHA256 từng file và SHA256 của ZIP. Công cụ chỉ lấy các thư mục được
chỉ định; bỏ `.secrets`, `.env`, database, backup, raw observations và `.venv`.
Không ghi đè gói cũ. Manifest lưu Git HEAD và trạng thái working tree để phân
biệt snapshot bàn giao với commit. Kiểm tra ZIP được chạy ngay sau khi tạo.
