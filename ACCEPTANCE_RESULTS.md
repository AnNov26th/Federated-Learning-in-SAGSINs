# Kết quả nghiệm thu — 31/10/2026

## Kiểm tra hệ thống

- 181/181 Python tests, 3/3 JavaScript tests PASS; `pip check` PASS.
- Startup bằng SQLite tạm mới PASS: database_ready=true, 178 node, API state
  dịch vụ và trang/assets trả 200. Không reset hoặc thay đổi MySQL vận hành.
- Đã kiểm tra cú pháp Python và `git diff --check`.
- Chưa xác nhận trên một máy mới cài dependency hoặc MySQL mới; startup dùng
  môi trường Python hiện tại và database mới. Cổng 8000 từ chối kết nối khi
  khảo sát; không coi kiểm tra SQLite là nghiệm thu MySQL live.

## Ma trận offline đã hoàn tất

5 seed × 5 tình huống × 30 tick; 75 hàng tổng hợp từng seed/chính sách,
4.500 trường hợp cặp client/tick cho mỗi chính sách. Các chính sách dùng cùng
inventory, seed, thời điểm, workload và trạng thái mạng. Model Trend/packed
được giữ từ experiment #13–17; không huấn luyện lại hoặc sửa dữ liệu client.

| Tình huống | QoS tĩnh | QoS current | QoS FL | Delivery current | Delivery FL |
|---|---:|---:|---:|---:|---:|
| Normal, 3 cặp | 96,444% | 96,444% | 96,444% | 99,444% | 99,444% |
| Nghẽn, 12 cặp | 72,111% | 75,556% | 75,556% | 92,791% | 92,795% |
| Mixed/outage, 6 cặp | 92,778% | 92,778% | 92,444% | 97,678% | 97,544% |
| Gaming/outage, 6 cặp | 8,889% | 7,556% | 7,556% | 97,544% | 97,544% |
| Smartphone tại GROUND, 3 cặp | 96,444% | 96,444% | 96,444% | 99,444% | 99,444% |

QoS cần đủ tốc độ và ngân sách trễ cả hai chiều sau khi trừ setup/handover.
Gaming dùng ngân sách demo 50 ms; delivery cao không có nghĩa đạt ngưỡng trễ.
Smartphone đặt ngay trạm nên không đại diện phủ sóng thiết bị tại mọi vị trí.
Không ghi nhận vi phạm capacity trong bất kỳ lượt nào.

| MAE link tham chiếu 1200 byte | Current | FL | Delta FL − current, CI bootstrap 95% |
|---|---:|---:|---|
| Normal | 0,131755 ms | 0,128864 ms | −0,002891 [−0,003172; −0,002570] ms |
| Nghẽn | 1,134428 ms | 1,115651 ms | −0,018777 [−0,019132; −0,018421] ms |
| Mixed/outage | 0,275595 ms | 0,269185 ms | −0,006411 [−0,006720; −0,006071] ms |

FL giảm MAE khoảng 1,66–2,33% tùy điều kiện, nhưng thay đổi QoS so current
bằng 0 trong 4 tình huống và −0,333 điểm phần trăm trong mixed/outage.
CI của delta QoS mixed/outage là [−0,778; 0] điểm phần trăm. Chưa có cơ sở
kết luận FL cải thiện QoS/delivery; cần thêm bài toán mà lợi thế dự đoán đủ
lớn để thay đổi quyết định tuyến một cách có ích.

CI lấy mẫu ghép cặp theo 5 seed, 5.000 lần, mang tính thăm dò, chưa hiệu chỉnh
nhiều so sánh. Mixed/congested dùng model huấn luyện normal. Frame dùng payload
tham chiếu 1200 byte để chấm link cho mọi dịch vụ; Gaming thay tốc độ/ngân sách
QoS, chưa hiệu chuẩn dự đoán riêng 256 byte. Không coi MAE link là sai số
end-to-end hoặc QoS ngoài thực địa.

## Chi phí training và tái lập

Training lịch sử có FL MAE 0,494950 ms, persistence 0,514404 ms và centralized
0,491884 ms. JSON body trung bình 763.130 byte/lượt, trong đó body training
119.438 byte. Các số này thuộc experiment đã lưu, không phải chi phí replay;
không gồm header/TCP/TLS. Số liệu từng seed, paired CI và phạm vi byte nằm trong
`storage/input/acceptance_20261031/training-*.json`.

Báo cáo: `storage/output/acceptance_20261031_final/report.html`, kèm CSV/JSON,
workload và methodology/hash. Kết quả tổng hợp từ các worker cục bộ; các hàng
hoàn chỉnh của nhánh bị dừng sau khi đủ normal/congested/mixed được giữ trong
provenance cùng hash. Chỉ kết quả đủ mọi seed/chính sách được đánh dấu
complete=true. Nhánh bị dừng không tính thêm như thí nghiệm độc lập.

Hướng dẫn cài đặt, demo, tái lập và tạo ZIP: [HANDOFF.md](HANDOFF.md).
