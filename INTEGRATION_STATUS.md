# Mốc tiến độ hợp nhất A/B — 26/10/2026

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
