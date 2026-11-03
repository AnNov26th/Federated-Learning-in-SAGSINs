# Rà soát logic, yêu cầu và training MySQL — 03/11/2026

> Cập nhật sau rà soát: bảng `network_observations` đã được phục hồi với 228.294
> bản ghi, nối lại khóa ngoại và kiểm tra đủ 11.950 observation ID được tham chiếu.
> Backend MySQL đã khởi động với `status=ok`, không còn cảnh báo cách ly; dữ liệu
> lịch sử đã đọc được. Phần phân tích P0 bên dưới ghi nhận lỗi trước phục hồi.
> Chi tiết và giới hạn độ chính xác backup: [DATABASE_RECOVERY_20261103.md](DATABASE_RECOVERY_20261103.md).

## Kết luận

Dự án có nền tảng mô phỏng FL nhiều tầng và giao diện tích hợp, có huấn luyện thật bằng PyTorch trên dữ liệu synthetic lưu ở MySQL. Chưa có đủ bằng chứng để kết luận Delay-Aware hiện tại giảm thời gian truyền thông SAGSIN, hoặc dự đoán FL cải thiện QoS dịch vụ. Lỗi tablespace chặn startup đã được xử lý bằng phục hồi bảng; các vấn đề logic/thực nghiệm bên dưới vẫn cần hoàn thiện.

Đã hoàn tất 7 experiment mới (#18–24), dùng nguyên dataset client MySQL đã có. Không sinh lại telemetry, không thêm observation/dataset client, không sửa experiment cũ. Đã sửa đường đọc lại dataset vì trước đây lựa chọn dataset cũ vẫn làm worker sinh/lưu bộ dữ liệu theo mã lượt mới.

## 1. Nguồn yêu cầu và mức đáp ứng

Đối chiếu `document/BÁO CÁO KẾ HOẠCH XÂY DỰNG HỆ THỐNG.docx`, đặc biệt mục 2, 9, 10, 22, 23 và 26; `document/Chức năng.txt`; báo cáo tạm; tài liệu bàn giao 31/10. Kế hoạch xác định MVP là FL + Random/Delay-Aware + mô phỏng latency; DP/NbFML là phần nâng cao. QR-DQN trong danh sách ý tưởng không được coi là điều kiện bắt buộc của MVP.

| Yêu cầu | Đánh giá thực tế |
|---|---|
| Mô phỏng SPACE/AIR/GROUND/SEA | Có inventory bốn tầng, graph, vị trí, contact, tài nguyên. SEA là radio trên biển, chưa phải âm học dưới nước; không bao phủ toàn bộ loại GEO/MEO/HAP/deep ocean trong ví dụ kế hoạch. |
| Pipeline FL | Có global model, local training, upload, weighted FedAvg, checkpoint, validation/test và audit. Đây là tính toán thật trên dữ liệu synthetic. |
| Dữ liệu cục bộ | Runtime phân tán dùng schema/account client riêng; coordinator nhận model và metric tổng hợp. Các tiến trình vẫn cùng máy, người có credential trên máy có thể đọc mọi schema. |
| Delay-Aware theo kế hoạch | Chưa tương đương thuật toán phân 4 nhóm latency và lịch aggregation của kế hoạch. Runtime mới chọn top-k theo chi phí tuyến. |
| So sánh Random/Delay-Aware | Có thể chạy đối chứng cùng dữ liệu, nhưng thiếu thời gian vòng mô phỏng phản ánh truyền model qua SAGSIN và độ phủ client theo thời gian. |
| Chỉ số kết quả | Có MAE/RMSE phù hợp bài toán hồi quy. Accuracy phù hợp MNIST, không nên dùng thay MAE cho network delay. Một số nhãn/metric thời gian cần sửa để phản ánh đúng phép đo. |
| Trực quan và phiên dịch vụ | Có địa cầu, chuyển động chung, hai đầu phiên, bandwidth, QoS, ACK và handover. Đây là phần mở rộng hữu ích nhưng không thay thế nghiệm thu nghiên cứu scheduling FL. |
| Privacy/NbFML/QR-DQN | Chưa có triển khai tương ứng. Gradient clipping tối ưu hóa model không phải cơ chế DP. Không tuyên bố đã tái hiện toàn bộ paper. |

Tài liệu nền: [FedAvg, McMahan et al.](https://proceedings.mlr.press/v54/mcmahan17a.html), [Space–Air–Ground–Sea Integrated Network with Federated Learning](https://www.mdpi.com/2072-4292/16/9/1640). Kết luận triển khai trong báo cáo này dựa trên code và dữ liệu của dự án; không suy kết quả thực nghiệm từ paper sang hệ thống hiện tại.

## 2. Phát hiện theo mức ưu tiên

### P0 — Backend không khởi động do bảng InnoDB lỗi

- Tái hiện bằng `.venv/Scripts/python.exe -m uvicorn backend.main:app --reload` ngoài sandbox: kết nối MySQL và lấy khóa được, dừng khi `create_all` kiểm tra bảng.
- MariaDB 10.4.32 trả lỗi 1932 khi `DESCRIBE` hoặc `SELECT` bảng `sagsins_db.network_observations`.
- Error log: expected tablespace ID 16, file chứa 4294967294. Bản sao file cho thấy page 0/2/3 có ID này, trong khi page 1 có ID 16. Chưa xác định nguyên nhân hoặc phạm vi record còn phục hồi được.
- 18 bảng khác trong DB chính đọc được ở lần kiểm tra; bảng lỗi vẫn có tham chiếu từ 11.950 observation ID khác nhau trong `network_round_predictions`.
- Đã sao chép `.ibd` (117.440.512 byte) và `.frm` vào `data/output/database_backups/network-observations-20261103/`. Đây là bản bảo toàn bảng lỗi, không phải backup toàn DB có tính nhất quán giao dịch.
- Backup SQL tìm thấy là 23/10, cũ hơn các dataset/tham chiếu hiện tại. Không tự drop/recreate, ghi đè .ibd, đổi recovery mode hoặc khôi phục toàn DB bằng bản cũ.
- Đã sửa thông báo startup để lỗi 1932 có hướng dẫn đúng; ứng dụng tiếp tục dừng khi DB chưa sẵn sàng.

Ý nghĩa lỗi: [MariaDB error 1932](https://mariadb.com/docs/server/reference/error-codes/mariadb-error-codes-1900-to-1999/e1932). Cần phục hồi trên bản sao và kiểm tra tham chiếu trước khi thay thế dữ liệu vận hành.

### P1 — Chi phí mạng chưa chi phối thời gian FL như yêu cầu nghiên cứu

`sagsin/experiment.py` chọn client theo đường đi nhưng gửi `/train` qua HTTP loopback. Chưa có bộ lập lịch sự kiện hoặc traffic shaping áp độ trễ/bandwidth SAGSIN vào upload/download model thực tế. `round_s` là wall time của HTTP/local training; không phải thời gian mô phỏng propagation + serialization + compute của từng client.

`distributed_runtime_service.py` còn ghi `record['wall_s'] * 1000` vào `Metric.communication_time_ms`, trong khi thời gian đó gồm cả local training. `FLClientRound.latency_ms`, energy và bandwidth đang được ghi 0 trong runtime này. Không dùng các trường này để kết luận tiết kiệm truyền thông/năng lượng.

Ưu tiên: lưu riêng wall-clock, thời gian compute, HTTP round trip, simulated model upload/download và simulated round makespan; bổ sung đối chứng đúng 4 nhóm latency/scheduling ratio nếu mục tiêu là tái hiện case study của kế hoạch.

### P1 — Lựa chọn top-k làm thiếu đại diện client

Tại seed 42/10 vòng/24 client mỗi vòng, Random chọn 138 client khác nhau, DelayAware và Predictive chỉ chọn 24. Hai chính sách sau không chọn SEA lần nào. Vì vậy cần báo cáo độ phủ, tần suất tham gia, MAE theo tầng và đánh đổi giữa tốc độ/đại diện; chưa thể gọi một lịch nhanh hơn là FL tốt hơn toàn mạng.

### P1 — Payload và phân phối dữ liệu giữa training và dịch vụ khác nhau

Dataset training hiện tại dùng payload tham chiếu 65.536 byte; `service_routing_service.build_frame` xây feature và chấm backbone bằng 1.200 byte. Truy cập hai đầu dùng payload dịch vụ riêng. Training dùng snapshot topology, còn service inference dùng vị trí/contact động; model normal được dùng cho live profile mixed.

Feature payload có tồn tại nhưng model `trend` chỉ dùng bốn thành phần xu hướng, không trực tiếp học mọi feature trong vector. Vì vậy không suy MAE test training sang MAE hoặc QoS của Gaming/Video Call. Cần dữ liệu nhiều payload và kiểm tra chuyển miền riêng, hoặc thống nhất định nghĩa reference target trong training/inference.

### P1 — Tái sử dụng dataset chưa đọc dữ liệu gốc: đã sửa

Trước sửa, `create_config` lấy lại metadata/topology nhưng `create_client` vẫn gọi `generate` và `save_local` dưới mã experiment mới. Kết quả có thể trùng nội dung do seed nhưng không đáp ứng yêu cầu dùng đúng dữ liệu MySQL đã lưu.

Sau sửa:

- `ExperimentConfig.dataset_run_id` xác định bộ dữ liệu nguồn.
- Worker chỉ SELECT dữ liệu và xác minh SHA256; không gọi generator/INSERT.
- Từ chối thiếu dataset, split rỗng, fingerprint lệch hoặc cấu hình sinh dữ liệu khác.
- Cho phép thay đổi rounds, model và policy training mà giữ nguyên seed/partition/profile/payload/topology dữ liệu.
- API chọn dataset cũ xác định lượt nguồn đã hoàn tất; không tự ghi lại metadata dataset nguồn.
- Offline baseline đọc đúng run nguồn khi sử dụng model retraining.

### P2 — Diễn giải số liệu và đối chứng

- Chia train/validation/test theo thời gian có khoảng đệm và FedAvg có trọng số sample là điểm đúng. Feature model không đưa nhãn tương lai vào input.
- Generator chỉ lấy cặp khi link active cả t và t+1. Đây là chọn tập mẫu có điều kiện theo availability tương lai, không phải bằng chứng model xử lý outage. Đánh giá gián đoạn cần giữ riêng benchmark có outage, không chỉ MAE trên các mẫu còn sống.
- Results đang ghi nhãn biểu đồ theo round là “Future test MAE/RMSE”, nhưng runtime mới ghi validation ở các vòng trung gian và test ở vòng cuối. Không đọc đường đó như một chuỗi test đồng nhất.
- Baseline centralized offline khớp tổng sample presentations nhưng dùng prefix của train pool cho epoch cuối chưa đủ. Chưa bảo đảm khớp đóng góp theo client/độ phủ; không dùng chỉ số đó để kết luận ưu thế FL một cách tuyệt đối.
- Default live model là experiment hoàn tất mới nhất theo ID, không có cơ chế xác nhận model đã được phê duyệt. Với nghiên cứu/demo nên chọn rõ experiment ID; chưa tự chọn/deploy model dựa trên test set.
- Benchmark routing hiện có chọn tại t/chấm t+1, ghép seed/workload, capacity dùng chung và có khoảng tin cậy theo seed. Đây là các điểm đúng; mô phỏng vẫn là fluid, chưa phải packet/RF hoặc media thật.

## 3. Các lượt training mới trên dataset MySQL hiện có

Đọc dữ liệu client của experiment #13–17, tương ứng seed 11/42/71/101/137 và dataset #12–16. Mỗi seed có 178 client, 16.554 train + 5.162 validation + 5.162 test. Giữ Trend/packed, non-IID/normal, 24 client/vòng, local epoch 1, learning rate 0,01, batch 64. Mỗi lượt mới khởi tạo model lại, chạy 10 vòng; không resume/ghi đè checkpoint cũ.

| Seed | Nguồn, 5 vòng | Experiment mới, 10 vòng | MAE 5 vòng (ms) | MAE 10 vòng (ms) | Persistence (ms) |
|---|---:|---:|---:|---:|---:|
| 11 | 13 | 18 | 0,503598 | 0,501869 | 0,521821 |
| 42 | 14 | 19 | 0,489037 | 0,488105 | 0,506358 |
| 71 | 15 | 20 | 0,510650 | 0,509524 | 0,530824 |
| 101 | 16 | 21 | 0,498340 | 0,496393 | 0,519267 |
| 137 | 17 | 22 | 0,473124 | 0,469182 | 0,493748 |
| Trung bình | | | **0,494950** | **0,493014** | **0,514404** |

MAE giảm thêm khoảng **0,39%** so với 5 vòng và thấp hơn persistence khoảng **4,16%** trên cùng task training. Delta ghép cặp 10−5 vòng = −0,001935 ms; bootstrap 95% theo 5 seed = [−0,002941; −0,001169] ms. Năm seed chỉ hỗ trợ kết luận thăm dò trên bộ synthetic này.

Fingerprint của toàn bộ 178 client mỗi seed khớp artifact nguồn. Lịch chọn client của 5 vòng đầu khớp lượt gốc. Không chọn hyperparameter/checkpoint theo kết quả test; báo cáo model cuối 10 vòng theo cấu hình đã đặt trước.

Body JSON tổng trung bình tăng lên 1.340.420 byte/lượt. Đây gồm các hạng mục giao thức được đếm, không gồm HTTP headers/TCP/TLS; tăng vòng có chi phí trao đổi và chỉ cải thiện MAE nhỏ. Không có kết luận QoS mới vì chưa chạy lại ma trận dịch vụ bằng model mới.

Đối chứng thêm trên cùng dataset #13/seed 42, 10 vòng:

| Chính sách | Experiment | Test MAE (ms) | Client khác nhau được chọn | Lượt chọn SEA |
|---|---:|---:|---:|---:|
| Random/FedAvg | 19 | 0,488105 | 138 | 23 |
| DelayAware | 23 | 0,488313 | 24 | 0 |
| Predictive | 24 | 0,488313 | 24 | 0 |

Hai lượt policy bổ sung là kiểm tra trên **một seed**, không phải so sánh thống kê nhiều seed. Wall time local không dùng để suy ra giảm độ trễ SAGSIN. Chưa có ưu thế MAE của hai policy so với Random trong kiểm tra này.

## 4. Kiểm chứng và bảo toàn

- 185/185 Python tests PASS, gồm kiểm thử đọc lại dataset, phát hiện fingerprint lệch, chặn thay seed dữ liệu và hướng dẫn startup 1932.
- 3/3 JavaScript tests PASS.
- `sagsin.release_check` PASS với SQLite tạm mới: 178 node, health database_ready=true. Đây không phải startup thành công trên MySQL đang lỗi.
- 7 experiment #18–24 đều COMPLETED; tổng round DB từ 155 thành 225.
- `network_datasets` vẫn 16. Truy vấn 178 schema xác nhận có **0** row dataset/observation mang mã của 7 lượt mới.
- Trạng thái 16 experiment cũ giữ nguyên (experiment #9 vốn FAILED); không reset DB hoặc tạo tài khoản mới.
- Các Uvicorn kiểm tra đã được dừng. Không để backend chạy với trạng thái DB lỗi.

Artifact chi tiết:

- `data/output/distributed_fl/retraining/mysql-existing-20261103-fedavg/runs.json`
- Cùng thư mục: `summary.json`, `summary.csv`, `selection-comparison.json`, `preservation-check.json`.
- `data/output/distributed_fl/retraining/mysql-existing-20261103-delay-aware/runs.json`
- `data/output/distributed_fl/retraining/mysql-existing-20261103-predictive/runs.json`
- Checkpoint/audit/network output riêng từng experiment ở `data/output/distributed_fl/experiments/<artifact_id>/`.

## 5. Thứ tự hoàn thiện phù hợp đề tài

1. Phục hồi bảng lỗi trên bản sao, kiểm tra 11.950 ID đang được tham chiếu, backup dữ liệu còn đọc được trước khi chuyển đổi. Không dùng backup 23/10 ghi đè toàn bộ DB hiện tại.
2. Tách thước đo thời gian thật và thời gian mạng mô phỏng; chạy Random so với lịch 4 nhóm latency/scheduling ratio như kế hoạch. Chưa cần mở rộng thêm chức năng giao diện.
3. Thêm cơ chế tránh bỏ đói tầng/client và báo cáo MAE theo tầng, độ phủ tham gia, chi phí truyền cùng lúc.
4. Thống nhất hoặc hiệu chuẩn payload/target, tách kiểm chứng dự đoán link khỏi hiệu quả route/QoS. Thu thập telemetry đo thật nếu muốn phát biểu về ứng dụng thực tế.
5. Nghiệm thu trên hai máy/client từ xa hoặc LAN, cấu hình địa chỉ client, TLS/auth, timeout và lỗi mạng thật. Khi đó mới đánh giá phân tán nhiều thiết bị; DP/secure aggregation vẫn là phần triển khai riêng.

Mức ứng dụng hiện tại phù hợp nhất là **nền tảng thực nghiệm và giảng dạy về FL trên mạng nhiều tầng**. Các bối cảnh như cảnh báo biển, kết nối vùng xa hoặc UAV relay là hướng ứng dụng hợp lý để xây kịch bản; hệ thống chưa được xác nhận để điều hành hạ tầng, bảo đảm cuộc gọi hoặc SLA ngoài thực địa.
