# Kho nội bộ của dự án

Thư mục này chứa dữ liệu cần để ứng dụng hoạt động, tái lập thí nghiệm và phục hồi.
Bộ dữ liệu gọn để xem/trình bày nằm ở ../data/README.md (7 file JSON, không có thư mục con).

- input/global_ground_nodes: inventory dùng khi seed/migrate database.
- input/acceptance_20261031: inventory và checkpoint đóng băng để nghiệm thu offline.
- input/network_benchmarks, input/service_benchmarks: nguồn benchmark lịch sử.
- output/distributed_fl: artifact runtime, checkpoint và kết quả FL; giữ đúng vị trí.
- output/acceptance_20261031_final: báo cáo nghiệm thu nhiều seed.
- output/exports: báo cáo/dataset lịch sử và ảnh minh chứng.
- output/network_benchmarks, output/network_demo: SQLite và kết quả benchmark/demo.
- output/database_backups, output/training_reset_backups: giữ nguyên bản sao phục hồi.
- output/teaching_evidence: bộ minh chứng đầy đủ trước khi rút gọn cho thư mục data/.
- output/releases: gói bàn giao và checksum.
- archive: các lượt kiểm thử/lịch sử đã nén.

Ngày 06/11/2026, toàn bộ cây data/input, data/output và data/archive được chuyển
nguyên vẹn sang storage/. Các đường dẫn trong code và tài liệu vận hành đã cập nhật.
Lịch sử MySQL không bị xóa hoặc tạo lại. Các đường dẫn ghi trong artifact/audit cũ
vẫn giữ giá trị ban đầu để bảo toàn chứng cứ; thay tiền tố data/ bằng storage/ khi tra.
layout-migration-20261106.json ghi đợt chuyển thư mục và các số đếm bảo toàn.

Các ZIP ở archive/cleanup-20261106 giữ đường dẫn con output/... nên khôi phục vào
storage (không giải nén vào data/):

```powershell
python -m zipfile -e storage/archive/cleanup-20261106/teaching-evidence-csv.zip storage
```

Chỉ khôi phục khi đường dẫn đích chưa có dữ liệu mới. Manifest dọn dẹp trước đây
vẫn ghi đường dẫn data/ cũ; đây là nhật ký lịch sử, không phải đường dẫn runtime.
