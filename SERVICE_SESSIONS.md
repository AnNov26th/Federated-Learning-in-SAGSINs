# Client dịch vụ, chuyển động và định tuyến QoS

> Bản bàn giao ngày 31/10 và lệnh demo/tái lập: [HANDOFF.md](HANDOFF.md).
> Kết quả bên dưới là benchmark lịch sử 27/10. Ma trận mới nằm trong
> `data/output/acceptance_20261031_final/`, bổ sung access capacity dùng chung,
> trừ setup/handover pause và khoảng tin cậy ghép cặp theo seed; không so trực
> tiếp delivery/QoS giữa hai phương pháp.

## Sử dụng

- Nhấn **Đặt client**, rồi chọn vị trí trên địa cầu. Nhấn lại nút hoặc Esc để hủy; có thể đặt liên tiếp. Mục **Nhập tọa độ & thiết bị** hỗ trợ nhập bằng bàn phím.
- Trong **Thiết lập**, chọn client nguồn, dịch vụ và client nhận. Video call/Gaming cần bên nhận chấp nhận. Emergency/Watch Video dùng máy chủ GROUND.
- Chọn **Công thức tĩnh**, **Telemetry hiện tại** hoặc **FL**. FL ghim checkpoint khi tìm được tuyến đầu tiên; thiếu checkpoint thì báo chờ/thất bại, không âm thầm đổi sang baseline.
- Kết thúc hoặc xóa client sẽ trả băng thông ngay. Tuyến cuối được giữ bằng nét đứt; xóa client sẽ ẩn cả tuyến liên quan và chặn token kết nối lại. Các bản ghi vẫn còn trong database để audit.
- Mở **Kết quả đối chứng FL** để xem bảng nhiều seed và báo cáo HTML/CSV đầy đủ.

Client dịch vụ thuộc `service_clients`, không được thêm vào `nodes`, `participants` hoặc pool FL. Một tab mô phỏng host các client logic bằng WebSocket riêng; chưa phải các máy vật lý hoặc tài khoản người dùng độc lập. WebSocket điều khiển thật, media/cảnh báo/ACK được mô phỏng; không dùng camera hoặc microphone.

## Một đồng hồ và một nguồn vị trí

`network_motion_service` tính vị trí từ inventory ban đầu và `network_clocks.sim_time_s`. Không ghi đè tọa độ gốc hoặc làm clock chạy nhanh hơn khi nhiều tab mở. SPACE dùng proxy quỹ đạo tròn với chu kỳ Kepler, hướng từ metadata và chuyển hệ quy chiếu theo vòng quay Trái đất; AIR/SEA dùng đường di chuyển vòng cục bộ với tốc độ 15/8 m/s. GROUND và RESEARCH_STATIC đứng yên.

API `/api/motion?scenario_id=...` gửi vị trí hiện tại và mẫu tiếp theo cách 2 giây. Trình duyệt nội suy, chỉ tiến tối đa tới mẫu tiếp theo rồi dừng khi mất cập nhật; không tự chạy quỹ đạo riêng. Đường nối và nền topology đọc cùng marker. Hình vẽ có thể lệch tối đa khoảng cửa sổ nội suy so với tick server; vị trí quyết định tuyến luôn được ghi lại tại `motion_clock_s`.

Graph dịch vụ tính lại tầm nhìn, khoảng cách và contact theo các vị trí này. Link radio mới chỉ xuất hiện khi hình học cho phép; link đã lưu INACTIVE không tự bật lại. Không tự tạo backhaul GROUND–GROUND mới. Contact động không thêm bản ghi inventory; capacity được quản lý theo ID contact chung. Nền topology chỉ vẽ hai lân cận/node để giảm rối, thuật toán dùng toàn graph khả dụng.

Đây là mô hình động học tổng hợp, không phải SGP4, mô phỏng RF/link budget hoặc bản sao hạ tầng thực địa. Các backhaul mặt đất đã lưu vẫn là giả định mô phỏng.

## QoS và chuyển tuyến

- Xét truy cập cả hai đầu, băng thông từng hop và hướng truyền; hai chiều dùng chung capacity trên link/node/client với flow cũ.
- Tìm tuyến trong ngân sách độ trễ trước; nếu không có thì chọn phương án khả dụng và báo chất lượng suy giảm. Video call dùng ngưỡng demo 2 Mbps mỗi chiều và 150 ms một chiều.
- Giới hạn chiều dài mặc định là `max(1500 km, 2 × khoảng cách mặt đất hai đầu + 2 × độ cao lớn nhất + 100 km)`. Đây là rào chắn độ vòng có khoảng dự phòng cho hai chặng truy cập, không phải cam kết stretch luôn nhỏ hơn 2.
- Tối đa 32 hop và 8 nhãn Pareto/node: heuristic tìm tuyến có ràng buộc, không tuyên bố tối ưu toàn cục.
- Xét lại mỗi 3 giây; giữ tối thiểu 10 giây và chỉ đổi thông thường khi tổng điểm cải thiện ít nhất 15%. Không chuyển từ tuyến đạt QoS sang tuyến không đạt. Tuyến mất vùng phủ/link hoặc vi phạm ràng buộc sẽ được xét lại ngay, không chờ hold time. Handover có pause 0,1 giây và audit lý do đổi/giữ.
- Mỗi tick cập nhật lại số liệu tuyến đang giữ. Capacity thực được kiểm tra bởi allocator dùng chung; nếu không đủ tốc độ, UI báo suy giảm. Chưa giải bài toán tối ưu đồng thời mọi tuyến và mọi phiên.

Weather/queue synthetic của live scenario dùng cùng seed 42/profile mixed, độc lập checkpoint đang chọn. Thay model không được thay trạng thái mạng. Trong benchmark, mỗi seed/profile được áp dụng giống nhau cho cả ba chính sách.

## Phiên và ACK

WebSocket `/api/service/clients/{id}/ws` xử lý register, heartbeat, start, accept, reject, end. Heartbeat 10 giây, lease 35 giây thời gian thực; bộ đếm và chờ tuyến dùng thời gian mô phỏng. Video/Gaming/Watch Video giữ tới khi ngắt hoặc mất kết nối quá hạn. Emergency/Message chỉ hoàn tất khi đích nhận dữ liệu, xử lý, gửi ACK ngược lại và ACK về client. Khi đang chờ xử lý/lan truyền không giữ bandwidth; ACK mất tuyến phải gửi lại trên tuyến hợp lệ. Server GROUND đã nhận cảnh báo được ghim, không dùng ACK từ server khác để giả thành công.

## Đối chứng đã chạy ngày 27/10/2026

Đã huấn luyện experiment #13–#17: seed 11, 42, 71, 101, 137; 5 vòng, 160 mẫu/client, pool 178 client, chọn 24/vòng, Trend/packed, non-IID, profile normal. Dữ liệu gốc vẫn tại MySQL riêng của client. MAE test trung bình: FL 0,49495 ms, persistence 0,51440 ms, centralized offline 0,49188 ms; đây là task/payload huấn luyện, khác phép đo application-link 1200 byte dưới đây.

Đánh giá mạng động dùng cùng inventory, ba cặp client cho mỗi seed, 45 tick/seed, cùng thời điểm và background. Model đóng băng trước đánh giá; cửa sổ bắt đầu sau training/test tại tick `samples_per_client + 20`. Chọn tại t, chấm geometry/capacity/delay tại t+1. Mỗi chính sách có 675 trường hợp ghép cặp. Future chỉ dùng để chấm, không đưa vào chọn tuyến. Static dùng chi phí danh định nhưng cũng chịu cùng điều kiện khả thi/QoS hiện tại.

| Chỉ số trung bình theo seed | Tĩnh | Hiện tại | FL |
|---|---:|---:|---:|
| MAE link tick kế tiếp | 1,1370 ms | 0,1410 ms | 0,1380 ms |
| Kết nối còn khả dụng | 99,8519% | 99,8519% | 99,8519% |
| Đạt QoS cả hai chiều | 99,8519% | 99,8519% | 99,8519% |
| Trễ một chiều trung bình, chỉ tuyến khả dụng | 71,49 ms | 72,25 ms | 72,22 ms |
| Số đổi tuyến/seed | 0,2 | 0,2 | 0,2 |

Không có vi phạm capacity. FL giảm MAE link khoảng 2,12% so với current, nhưng chưa tăng tỷ lệ QoS/delivery; static còn có độ trễ trung bình thấp hơn trong khảo sát này. Không suy ra ưu thế thống kê hoặc FL luôn tốt hơn. Đây là 5 seed/profile normal, chưa phải toàn ma trận tải/dịch vụ/thiết bị. Các chính sách chia sẻ nguồn background và workload; đây là đối chứng route/allocator fluid, không phải cuộc gọi media thực.

Phép đối chứng mạng động dùng bước 1 giây và không trừ pause handover 0,1 giây trong số liệu delivery; phiên live có trừ pause đó. Do đó không đối chiếu trực tiếp throughput live với benchmark. Số đổi tuyến trong khảo sát này bằng nhau giữa cả ba chính sách.

Nguồn: `data/output/distributed_fl/benchmarks/20261027T034040Z/`, phần mạng động tại `dynamic-services/`. Có runs/aggregates CSV+JSON, workloads, inventory, paired.json và methodology.json. Input riêng tại `data/input/service_benchmarks/20261027T034040Z/`. API báo cáo: `/api/service/benchmark?scenario_id=6`; báo cáo HTML: `/api/service/benchmark/report?run=20261027T034040Z`.

## Tái lập và nghiệm thu

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/service-path.test.mjs
.\.venv\Scripts\python.exe -m sagsin.service_smoke
.\.venv\Scripts\python.exe -m sagsin.benchmark --seeds 11 42 71 101 137 --rounds 5 --samples 160 --clients 24 --profiles normal
.\.venv\Scripts\python.exe -m sagsin.service_route_benchmark data/output/distributed_fl/benchmarks/20261027T034040Z --ticks 45
```

177/177 Python tests và 3/3 JavaScript tests PASS. Bao gồm mất vùng phủ khi vệ tinh di chuyển, observer không tăng clock, model không đổi weather, QoS thay thế tuyến rẻ nhưng quá trễ, chặn độ vòng, hysteresis và các kiểm thử phiên/ACK/capacity cũ.

Smoke thật: call #18 đạt 2 Mbps mỗi chiều, Emergency #19 có ACK. UI call #20 tiếp tục truyền trên graph động, đã thay tuyến khi điều kiện đổi và đã kết thúc. Audit `data/output/distributed_fl/acceptance/shared-motion-qos.json` đối chiếu tọa độ mọi node trong tuyến với hàm backend tại đúng tick: sai khác 0 độ. Các client sự kiện vẫn tách pool FL, database node vẫn 184 (scenario toàn cầu có 178).
