# Phục hồi dữ liệu MySQL — 03/11/2026

## Kết quả

Bảng `network_observations` đã được phục hồi và đưa về tên cũ sau khi người dùng
xác nhận cho phép thay bảng hỏng. Không thay thế toàn bộ database.

- 228.294 bản ghi, ID liên tục 1–228294; AUTO_INCREMENT tiếp theo 228295.
- 223.907 bản ghi lấy từ các trang clustered index còn đọc được trong bản sao `.ibd`.
- 4.387 bản ghi đầu lấy từ backup SQL `before-links-training-20261023-003435.sql`.
- 23.173 bản ghi trùng giữa file và SQL đã đối chiếu; dữ liệu FLOAT trong dump
  được so ở độ chính xác 6 chữ số có nghĩa mà dump lưu lại.
- 46.280 bản ghi dataset #3 đối chiếu với export CSV: ID, client, sequence,
  split, feature và target đều khớp theo độ chính xác export.
- Sau nhập MySQL, đã đọc lại và đối chiếu toàn bộ 228.294 bản ghi với bản phục
  hồi: dữ liệu JSON và các giá trị float32 của bản phục hồi giữ nguyên.
- Khóa ngoại `network_round_predictions.observation_id` đã nối lại và kiểm tra:
  11.950 ID khác nhau được tham chiếu, không thiếu ID nào.

| Dataset | Số bản ghi |
|---|---:|
| 1 | 27.560 |
| 2 | 74.760 |
| 3 | 46.280 |
| 4 | 49.484 |
| 5 | 18.090 |
| 6 | 12.120 |

Các bảng lõi giữ nguyên số hàng sau thay bảng: 23 experiment, 225 FL round,
16 dataset, 12.040 round prediction, 184 node và 494 link.

## Sự cố và xử lý

MariaDB 10.4.32 báo lỗi 1932: engine chờ tablespace ID 16 nhưng một phần file có
ID 4294967294. Chưa xác định nguyên nhân gây hỏng; không kết luận do thao tác
của người dùng hoặc Spec Kit.

Đã tạo bảng phục hồi riêng và kiểm chứng trước khi thay thế. MariaDB từ chối
đổi tên bảng hỏng với lỗi 1025/155; lần thử đó không chuyển bảng phục hồi vào dùng.
Sau khi được người dùng chấp thuận, đã giữ backup rồi bỏ khóa ngoại đi vào bảng,
DROP bảng hỏng, đổi tên bảng phục hồi và thêm lại khóa ngoại có kiểm tra ràng buộc.
Không tắt `foreign_key_checks` và không tạo nhãn/telemetry mới để lấp dữ liệu.

**Giới hạn:** 4.387 target lấy từ SQL backup chỉ có độ chính xác số FLOAT theo
dump cũ, khoảng 6 chữ số có nghĩa. Không khẳng định khôi phục bit-for-bit các
giá trị gốc trước khi dump cho phần này. 223.907 bản ghi từ file giữ độ chính xác
float32 đọc được. Các số liệu nghiệm thu/model đã lưu trước đây không bị ghi đè.

## Kiểm chứng ứng dụng

Đã chạy `uvicorn backend.main:app --reload` trên MySQL hiện tại. Startup hoàn tất,
`/api/health` trả `status=ok`, `database_ready=true`, warnings rỗng. Trang chủ,
metadata của cả 16 dataset, raw observations của dataset #1/#6, experiment
cũ #2 và mới #24, nodes và service state đều trả HTTP 200.

Bộ kiểm thử gần nhất: 195 Python tests PASS, 3 JavaScript tests PASS.

## Backup và audit

Các file dưới đây nằm trong `data/output/database_backups/network-observations-20261103/`
và được ignore khỏi Git:

- `network_observations.ibd`, `network_observations.frm`: bản sao file lỗi trước sửa.
- `before-promotion-healthy-tables.sql`: backup logic các bảng còn đọc được,
  gồm bảng phục hồi riêng trước khi chuyển tên; 90.188.119 byte.
- `recovered-v2.sqlite`, `recovered-v2.json`: bản phục hồi cục bộ và nguồn/hash.
- `candidate-validation.json`, `staging-validation.json`,
  `pre-promotion-validation.json`: các bước kiểm chứng.
- `promotion-plan.sql`, `promotion-journal.json`, `promotion-result.json`:
  kế hoạch đã được phê duyệt và nhật ký thao tác thực tế.
- `network_round_predictions-before.sql`: định nghĩa bảng trước nối lại FK.
- `live-validation.json`: kiểm tra API sau phục hồi.

`backend/database/recover_observations.py` chỉ trích xuất sang file cục bộ,
không tự thay bảng MySQL. Không chạy lại kế hoạch DROP/RENAME sau khi đã hoàn tất.
