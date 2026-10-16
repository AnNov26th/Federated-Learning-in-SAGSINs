# Định tuyến sự kiện dựa trên model FL

Màn hình Simulation dùng `POST /api/routing/event` để tính đường đi trên snapshot database. Không còn thuật toán định tuyến riêng ở trình duyệt. `GET /api/routing/context` cung cấp scenario và checkpoint FL có thể dùng.

## Khi đặt một điểm

1. Lấy node ACTIVE hợp lệ thuộc scenario đã chọn. Không đi qua node hoặc link của scenario khác.
2. Chọn node tiếp cận gần nhất nằm trong bán kính cấu hình. Node mặt đất/biển dùng khoảng cách cung trên mặt cầu; node có độ cao dùng khoảng cách không gian và phải ở trên đường chân trời. Chặng từ điểm đặt đến node là giả định phủ sóng, không phải link đã đo.
3. Đích mặc định là GROUND ACTIVE khác node tiếp cận. Có thể chọn GROUND cụ thể, kể cả chính node tiếp cận nếu muốn mô phỏng xử lý tại chỗ.
4. Dùng link ACTIVE đã lưu hoặc topology ước tính do người dùng chọn. Hai chế độ không tự chuyển đổi. Link đã lưu được xem là kết nối do người dùng cấu hình; không tự áp đặt mô hình radio lên một link có thể đại diện cho kết nối có dây.
5. Tạo trạng thái kênh mô phỏng từ bandwidth/latency của link và hai node, khoảng cách, network profile của model, cùng tải người dùng chọn. Công thức tải/loss bám theo bộ sinh dataset hiện có. Loại hướng truyền không đủ băng thông theo dịch vụ.
6. Với chính sách Predictive, chọn checkpoint mới nhất của experiment FL **COMPLETED**, task `network_delay`, cùng scenario, có round đã aggregate, feature version và target phù hợp. Có thể chọn experiment cụ thể. Không dùng model chưa huấn luyện, experiment Centralized hoặc checkpoint của scenario khác; thiếu model thì báo rõ.
7. Batch inference cho mọi hướng truyền hợp lệ bằng `NetworkDelayRegressor` đã lưu. Dijkstra dùng tổng trọng số cộng được để tìm đường tới GROUND có chi phí nhỏ nhất. Một lượt tìm kiếm xét tất cả đích, không thử lần lượt theo băng thông của đích.
8. Chạy Dijkstra theo công thức tĩnh trên cùng topology, tải, ingress, tập đích và ràng buộc băng thông. Hiển thị cả hai đường và dùng **cùng model** chấm hai tuyến để đối chiếu. Không khẳng định tuyến Predictive luôn có tổng RTT thấp hơn: mục tiêu còn gồm phạt băng thông.

## Chi phí và ràng buộc

`cost(path) = Σ(w_delay × RTT_proxy_ms + w_capacity × 100 / bandwidth_Mbps)`

RTT công thức là download/upload payload FL qua kênh đối xứng, điều chỉnh loss; RTT dự đoán lấy từ checkpoint. Bandwidth mỗi hop là min bandwidth của link và hai node, nhân hệ số network profile và `(1 − 0.65 × load)`. Phạt bandwidth **cộng theo từng hop**, không phải phạt bottleneck; bottleneck được báo riêng. Điều này giữ cho Dijkstra đúng với hàm mục tiêu.

| Dịch vụ | w_delay | w_capacity | Băng thông tối thiểu (Mbps) |
|---|---:|---:|---:|
| Message | 0.55 | 0.10 | 0.05 |
| Video Call | 0.45 | 0.40 | 2 |
| Watch Video | 0.20 | 0.75 | 5 |
| Gaming | 0.80 | 0.08 | 1 |
| Emergency | 1.00 | 0.15 | 0.10 |

Đây là chính sách mô phỏng của ứng dụng, không phải SLA hay chuẩn dịch vụ. Emergency ưu tiên độ trễ trong mục tiêu; chưa có cơ chế đặt trước tài nguyên hoặc ưu tiên hàng đợi giữa các sự kiện.

Topology ước tính chọn tối đa hai hàng xóm mỗi node trước khi hợp nhất các cặp đối xứng. Giới hạn khoảng cách: có SPACE 5.000 km, có AIR 1.500 km, còn lại 500 km; node có độ cao phải thỏa điều kiện đường chân trời. Không thêm cầu nối để ép toàn mạng liên thông. Chế độ này không ghi database. Nút “Sinh & lưu link lân cận” là thao tác riêng, sử dụng API tạo link hiện có, giới hạn trong scenario đang chọn.

## Model thực sự dự đoán gì?

Checkpoint hiện được huấn luyện từ telemetry mô phỏng của từng client/kênh đại diện, target `next_tick_model_round_trip_ms`: RTT của **payload FL huấn luyện** ở tick tiếp theo. Dataset chưa được thiết kế và kiểm chứng như bộ đo độ trễ từng hop hay độ trễ ứng dụng đầu-cuối.

Vì vậy áp dụng model lên từng hop hiện là **chỉ số thay thế cho xếp hạng tuyến mang tính thực nghiệm**. UI ghi rõ tổng RTT/hop, payload, experiment, round, MAE/validation MAE, chất lượng so với persistence và lớp ngoài dữ liệu huấn luyện. Không gọi con số đó là latency Video Call/Gaming; không cộng chặng tiếp cận vào tổng dự đoán vì chưa có telemetry cho chặng này. Load, jitter, loss và observed RTT đầu vào được dựng từ công thức, không được quảng bá là phép đo thời gian thực. Không đọc target tương lai, nhãn online/test hay prediction audit để quyết định tuyến.

Để kiểm chứng tối ưu độ trễ ứng dụng đầu-cuối cần thu thập/sinh dataset theo từng link ở t và t+1, nhiều payload ứng dụng, trạng thái hàng đợi, lịch sử tải theo link và đo end-to-end. Sau đó huấn luyện/đánh giá model với target phù hợp, so sánh trên cùng điều kiện và dữ liệu giữ lại. Phiên bản này chưa triển khai DRL/QR-DQN.

## Sử dụng và kiểm tra

- Mở Simulation → chọn scenario → Dự đoán bằng model FL → chọn checkpoint hoàn tất hoặc tự chọn mới nhất → chọn sự kiện → nhấn trên địa cầu. Có thể nhập tọa độ bằng bàn phím trong cấu hình mở rộng.
- Thay đổi cấu hình chỉ áp dụng cho điểm mới. “Cập nhật mạng & tính lại” áp dụng cấu hình hiện tại cho toàn bộ điểm, tải lại node/link/model, bỏ tuyến cũ nếu cập nhật thất bại.
- Bảng phân tích có từng hop, tuyến công thức, nguồn dữ liệu và hoạt ảnh truyền minh họa 5 giây/lượt. Thiết bị tạm dừng tại snapshot DB khi xem tuyến; không thể suy ra routing liên tục theo quỹ đạo từ hoạt ảnh này.
- Kéo địa cầu không tạo sự kiện; Esc hủy chế độ đặt điểm; xóa điểm cũng giải phóng geometry/material. Request cũ không được ghi đè kết quả sau khi tính lại hoặc xóa điểm.

Chạy `.venv/Scripts/python.exe -m unittest discover -s tests -p test_routing.py -v`. Kiểm thử dùng SQLite riêng, bao gồm checkpoint PyTorch thật, huấn luyện FL rồi gọi routing và đối chiếu inference, đường thay đổi theo prediction, mất kết nối, vùng phủ, băng thông, node OFFLINE và cách ly scenario.
