# Mốc tiến độ hợp nhất A/B — 26/10/2026

## Bàn giao 31/10/2026

- Nghiệm thu cuối: 181 Python tests + 3 JS tests PASS; pip check PASS.
- Ma trận hoàn tất 25 lượt, 4.500 trường hợp/chính sách. FL giảm MAE nhưng
  chưa tăng QoS; mixed/outage giảm QoS 0,333 điểm phần trăm so current.
  Chi tiết và CI: ACCEPTANCE_RESULTS.md. Chưa nghiệm thu MySQL live hôm nay.

- Startup/API trên SQLite mới: PASS, 178 node, database_ready=true, trang và asset
  dịch vụ trả 200; không dùng MySQL vận hành. Bộ kiểm tra: sagsin.release_check.
- Đóng gói inventory và năm checkpoint #13–17 để replay offline, không chứa
  credential/raw observations. Thêm acceptance_matrix với seed bootstrap CI,
  tải đồng thời, contact outage, Gaming và smartphone; kết quả chỉ hợp lệ khi
  methodology.complete=true. Nguồn kết quả cuối: data/output/acceptance_20261031_final.
- Hướng dẫn hiện hành: HANDOFF.md. Nội dung ghi server đang chạy và usage ở các
  mốc bên dưới là lịch sử, không phải trạng thái runtime/usage hôm nay.
- Gói source/demo dùng sagsin.release_bundle: whitelist source/input/report,
  SHA256 từng file và ZIP, không có database/backup/.env/.secrets.

## Kiểm tra tiếp ngày 27/10/2026

### Hoàn tất tối ưu 1/2/3: chuyển động chung, QoS, đối chứng FL

- Vị trí SPACE/AIR/SEA tính tại backend bằng network_clocks; API /api/motion cấp hai mẫu cách 2 giây để trình duyệt nội suy có giới hạn, không tự chạy quỹ đạo riêng. Graph dịch vụ và nền topology dùng cùng tầm nhìn/khoảng cách; contact radio xuất hiện/mất theo vị trí. Inventory gốc không bị ghi đè; không tự tạo backhaul mặt đất mới. Đây là động học tròn/waypoint proxy, chưa có SGP4/RF/link budget.
- Engine service_routing_service ưu tiên tuyến trong ngân sách QoS, kiểm tra hai đầu và giới hạn độ vòng, 32 hop/8 nhãn Pareto. Xét lại 3 s, hold 10 s, ngưỡng cải thiện 15%; mất vùng phủ bỏ hold, có audit handover/pause 0,1 s. Live weather seed 42/mixed tách khỏi checkpoint để đổi model không đổi trạng thái mạng.
- Đã chạy experiment #13–17, 5 seed, 5 vòng, pool 178/24 client mỗi vòng, 160 mẫu/client, Trend/packed, non-IID/normal. Benchmark graph động: 3 cặp client ×45 tick×5 seed =675 trường hợp/chính sách, chọn tại t/chấm tại t+1, model đóng băng. MAE link: static 1,136996 / current 0,140963 / FL 0,137968 ms. QoS cả ba 99,8519%; delay thành công trung bình 71,49 /72,25 /72,22 ms. FL giảm MAE ~2,12% so current, chưa tăng QoS hoặc delivery, không tuyên bố ưu thế routing phổ quát.
- Báo cáo trong data/output/distributed_fl/benchmarks/20261027T034040Z/dynamic-services; input inventory/workload tại data/input/service_benchmarks/20261027T034040Z. UI Thiết lập → Kết quả đối chứng FL và API /api/service/benchmark?scenario_id=6 có bảng và link báo cáo.
- 177/177 Python tests và 3/3 JS tests PASS. Smoke call #18 hai chiều 2 Mbps, Emergency #19 ACK. UI call #20 chạy trên graph động, đã đổi tuyến theo điều kiện và kết thúc; audit shared-motion-qos.json kiểm tra tọa độ route tại tick ghi nhận, sai khác 0 độ. Không tăng Node theo client dịch vụ (DB vẫn 184). Xem SERVICE_SESSIONS.md cho phương pháp/giới hạn/tái lập.

### Client dịch vụ và phiên hai đầu đã triển khai

Cập nhật giao diện tiếp: bỏ dropdown chỉ có một chế độ, thay bằng nút Đặt client bật/tắt; đặt liên tiếp cho tới khi nhấn lại hoặc Esc. Danh sách thiết kế thành hàng gọn có biểu tượng, online, tọa độ, số phiên và thùng rác. Xóa client đánh dấu deleted (migration bổ sung cho DB cũ), kết thúc phiên liên quan và trả bandwidth ngay, ẩn route/client khỏi state và chặn token đăng ký lại; giữ bản ghi audit. Đã thử bật/tắt, thả, Esc và xóa client thử trên UI; 168/168 Python tests và 3/3 JS motion tests PASS.

Cập nhật tiếp: danh sách client dạng thẻ trực tiếp, chọn/định vị như danh sách sự kiện. Đường nối dịch vụ có hook animation riêng chạy sau cập nhật vị trí node, đọc marker hiện tại thay vì vector snapshot đóng băng; giữ tuyến cuối theo từng cặp client/dịch vụ sau khi kết thúc, nét đứt cho lịch sử, chấm dữ liệu cho phiên đang truyền. Không đổi allocator hay cơ chế trả bandwidth. Ba kiểm thử JavaScript mới xác nhận bám node di chuyển/thay marker, bám hai đầu client, fallback rồi lấy marker mới; đã kiểm tra UI chọn thẻ và không có lỗi console. Chuyển động chỉ là hiển thị, không tự đổi vị trí địa lý database hoặc chứng nhận RF/quỹ đạo liên tục.

Xem `SERVICE_SESSIONS.md` để thử. Client thả trên địa cầu lưu trong service_clients, không thêm Node/Participant hay client FL. Giao diện chọn thiết bị, dịch vụ, client đích, công thức tĩnh/FL; WebSocket riêng cho register/heartbeat/start/accept/reject/end. Hai chiều call dùng chung allocator/link/node/access với flow cũ. Video/Gaming giữ tới khi ngắt hoặc mất kết nối quá hạn; Emergency/Message chỉ hoàn tất sau xử lý tại đích và truyền ACK ngược lại, không giữ bandwidth khi chờ. Watch Video truyền từ GROUND xuống client. Lịch sử route được giữ sau kết thúc, hiển thị quality vượt ngân sách demo. Tất cả là media/ACK mô phỏng, không gọi camera hay âm thanh thật.

Nghiệm thu thật: scenario #6, hai client dịch vụ #1/#2 gần GND-COL-001 và GND-IDN-001 ở hai bán cầu. Call #5 đạt 2 Mbps mỗi chiều qua nhiều tick, chủ động kết thúc; Emergency #6 nhận ACK và trả bandwidth. UI call #7 dùng FL mới nhất (#12 tại lúc thử), hai chiều 2 Mbps, tuyến khoảng 27.051 km/chiều và khoảng 271,2 ms một chiều, hiển thị suy giảm chất lượng; đã kết thúc, không để flow test giữ tài nguyên. Node database vẫn 184, không tăng theo client dịch vụ. Phiên #4 bị gián đoạn do reload giữ trạng thái FAILED; không xóa lượt lỗi. Đã dừng đúng server nền cũ do agent tạo đang giữ cổng sau startup lỗi, để server terminal của người dùng tiếp tục phục vụ.

Minh chứng: `data/output/distributed_fl/acceptance/service-sessions.json`, `service-call-ui.png`. Đã thử thả client trực tiếp lên globe; client thử #3 chưa có phiên đã được dọn, giữ hai client demo. Heartbeat MySQL dùng DOUBLE, có nâng cột FLOAT cũ để tránh lệch hàng chục giây ở Unix epoch. Đã xử lý JSON allocation bị autoflush trước service tick bằng flag_modified, kiểm thử chung flow cũ/mới xác nhận không vượt capacity. Mốc kiểm thử cuối được ghi trong SERVICE_SESSIONS.md.

### Đã khôi phục MySQL và startup lúc khoảng 09:03

Log console xác định bảng quyền Aria `mysql.db` hỏng index, khiến MariaDB tự thoát; không đơn thuần là backend chờ. Đã sao lưu toàn bộ schema hệ thống `mysql`, cấu hình và Aria logs vào `data/output/database_backups/mysql-system-20261027-090111/`. `aria_chk --recover` không sửa được header nên đã phục hồi trên bản sao riêng bằng `REPAIR TABLE mysql.db USE_FRM`, CHECK TABLE OK, đọc được 474 dòng quyền. Instance sửa chỉ mở named pipe, tắt TCP và InnoDB, không dùng datadir chính. Đã shutdown instance sửa, zerofill bảng đã phục hồi và thay riêng db.MAI/db.MAD khi MySQL chính dừng. Không thay user/global_priv hoặc dữ liệu ứng dụng.

MySQL bình thường đã `ready for connections` tại 3306. Backend dùng .venv, --reload chạy nền tại 8000, `Application startup complete`, health `database_ready=true`. Database chính đọc được 184 node và 11 experiment; client mẫu đọc được 524 observations, account backend vẫn bị từ chối SELECT raw data của client. Chưa kiểm tra toàn bộ bảng/client; cảnh báo InnoDB của bảng phpMyAdmin trước đó chưa được sửa. Log phục hồi và backend trong `data/output/distributed_fl/acceptance/*restored*.log`.

Đã thêm timeout kết nối/đọc/ghi MySQL, log theo bước startup và đóng connection khi lấy khóa thất bại. Bộ kiểm thử sau sửa đạt 151/151 (chạy ngoài sandbox vì threadpool sandbox bị chờ). Tình trạng MySQL/backend không sẵn sàng ghi dưới đây là quan sát trước phục hồi.

- CSV dữ liệu lịch sử vẫn còn trong `data/input/network_benchmarks`; bản xem nhanh có cột tại `data/output/exports/network_dataset_3_20261023/preview_20.csv`. Runtime HTTP mới giữ raw observations tại MySQL riêng từng client, không xuất tập trung qua coordinator.
- Chọn toàn bộ pool không tự tạo link. Tuy nhiên chưa có giới hạn tổng chiều dài/độ vòng của tuyến. GROUND đích không đồng nghĩa ingress chỉ được GROUND; profile thiết bị còn cho phép AIR/SEA hoặc SPACE tùy loại.
- Audit độc lập database trên result snapshot `94f18a5f7b0b488e895a88e43f6606c4`: 178 node, 460 link; 177 nguồn đến GND-CAN-002 qua 60 tick = 10.620 trường hợp. Không mất tuyến, lặp node, dùng edge unavailable hoặc vượt giới hạn khoảng cách từng link; tối đa 13 hop, tuyến dài nhất 32.473,354 km. Chỉ kiểm tra current-telemetry routing, không xác nhận mọi FL-policy route hay RF/LOS thực địa. Cần đánh giá độ vòng và lựa chọn ground đích trước khi khẳng định mọi tuyến hợp lý.
- Tái lập: chạy `python data/output/distributed_fl/acceptance/audit_saved_routes.py` với PYTHONPATH trỏ project root. Kết quả: `saved-route-audit.json`, `saved-routes.csv` cùng thư mục. Đây là audit snapshot lịch sử, không phải benchmark nhiều seed mới.
- Lúc kiểm tra backend 8000 không lắng nghe; MySQL nhận TCP 3306 nhưng không trả handshake trong 5 giây (PyMySQL 2013). Benchmark mới chưa chạy; không restart/kill MySQL hay thay đổi database. Toàn bộ test suite hiện tại chưa xác nhận lại do lượt chạy bị chờ; đã dừng các tiến trình kiểm tra bị treo do lượt này tạo. Mốc 146 PASS dưới đây là nghiệm thu hôm qua.
- Kiểm tra offline hôm nay: 18/18 tests thuộc AllocationTests, DataAndRoutingTests, FedAvgAndCheckpointTests PASS; TEMP/TMP đặt trong thư mục được phép ghi để tránh lỗi quyền thư mục tạm sandbox. Không tính lượt suite bị treo là PASS.

## Nghiệm thu đã lưu ngày 26/10/2026

Giữ UI gốc A, thay lõi bằng HTTP FL, dữ liệu client riêng, predictor/codec và allocator kế thừa B. Không còn trang/menu phân tán riêng. Quy mô toàn cầu giữ 178 node (96 SPACE / 12 AIR / 50 GROUND / 20 SEA), 460 link ACTIVE, pool 178 client; 4 tiến trình host các nhóm client logic.

Đã qua 146 kiểm thử. Server của người dùng đang chạy tại http://127.0.0.1:8000/ với --reload và đã nhận bản mới; không dừng server này. Các server kiểm thử 8012 đã dừng. MySQL đã bật. Account app riêng chỉ có quyền DB gốc; credential không được đưa lên Git.

Run #10 đã hoàn tất 2 vòng trên server 8000, audit tensor FedAvg và phân quyền DB PASS. Run #9 lỗi worker startup được giữ; đã thêm log và retry đúng một lần trước vòng đầu. Run #8 trước đó đã hủy/resume từ vòng 1 đến 8. Event #48 dùng model #7, truyền đủ 0,5 Mbit rồi giải phóng bandwidth. UI Results cũ hiển thị baseline, tám đối chứng, replay đã thử bằng bàn phím. Ảnh: data/output/distributed_fl/unified-results.png.

Nghiệm thu mới nhất:
{
  "experiment_id": 10,
  "pool": 178,
  "nodes": 178,
  "links": 460,
  "completed_rounds": 2,
  "fedavg_audit": "exact tensor equality",
  "main_database_isolation": "passed",
  "resume": {
    "experiment_id": 11,
    "retained_rounds": 1,
    "completed_rounds": 8
  }
}

Chưa chạy toàn ma trận benchmark nhiều seed; không tuyên bố FL luôn tốt hơn baseline. Chưa kiểm chứng LAN/TLS/DP/RF/quỹ đạo. Không giảm topology theo max_workers. Các thay đổi chưa commit; README đã có thay đổi từ người dùng trước khi làm, giữ phần đó. Xem DISTRIBUTED_FL.md để tra kiến trúc và lệnh chạy.

Usage được đọc khi người dùng yêu cầu dừng nếu hết: 98% cửa sổ 5 giờ, 15% tuần. Kiểm tra lại usage trước khi mở thêm việc lớn.
