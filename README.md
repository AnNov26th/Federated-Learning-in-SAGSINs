# Federated Learning in SAGSINs

Chương trình chính mô phỏng mạng Space–Air–Ground–Sea, huấn luyện FL dự đoán độ trễ từ dữ liệu mạng trong database và so sánh chính sách chọn participant.

## Thư mục dữ liệu

Dữ liệu nguồn/inventory, mẫu benchmark và request nằm trong `data/input/`.
Metric, checkpoint, báo cáo, minh chứng và backup nằm trong `data/output/`.
Xem [hướng dẫn input/output](data/README.md) để tra từng loại file và cách tạo
lại báo cáo. Database MySQL chính giữ nguyên; không huấn luyện lại hoặc reset
dữ liệu khi tổ chức thư mục.

## Định tuyến từ node gần và khả thi (25/10/2026)

Đã đối chiếu commit gần nhất `768d196` (Sửa lại định tuyến). Simulation giữ mạng toàn cầu 178 node và mọi dataset/checkpoint/cấu hình huấn luyện; chỉ đổi cách chọn tiếp cận mặc định `network_gateway`:

1. Lọc node ACTIVE cùng scenario, tầm nhìn và tầm tiếp cận mô phỏng theo lớp: GROUND 50 km, SEA 200 km, AIR 1.500 km, SPACE 5.000 km; không giả lập radio điện thoại/camera/laptop.
2. Trừ băng thông đã cấp, kiểm tra node/link còn đủ cho dịch vụ; tìm các node có đường tới GROUND đích trên graph khả thi.
3. Chọn node gần nhất theo khoảng cách 3D trong các ứng viên đó. Node gần nhưng cô lập hoặc thiếu dung lượng bị bỏ qua. FL và đối chứng dùng cùng node đầu vào.
4. Dùng checkpoint FL hiện có để tối ưu tuyến từ node đầu vào, cùng trọng số độ trễ/băng thông/khoảng cách; không dùng nhãn tương lai. Không tự điều động node hoặc nối thẳng tới GROUND xa.

Đồ thị kiểm tra lại khoảng cách từ vị trí snapshot, tầm nhìn và giới hạn theo lớp. Link terrestrial đã lưu được giữ trong giới hạn backbone; không tự tạo các link GROUND–GROUND xa trong topology adaptive. Nếu không có truy cập hoặc tuyến hợp lệ, trả nguyên nhân rõ ràng. Thả ở mọi tọa độ là được; không cam kết mọi tọa độ đều có vùng phủ/dung lượng trong mọi trạng thái mạng.

Báo cáo `data/output/exports/global-gateway-check.json` và ảnh `global-gateway-demo.png` là minh chứng **chế độ truy cập không giới hạn trước lần sửa này**, không dùng để đánh giá logic gần/khả thi hiện tại. Khu vực nghiên cứu 6 node vẫn là lựa chọn riêng; lịch sử/dữ liệu đầu vào được giữ lại.

## Khu vực nghiên cứu và phiên sự kiện hữu hạn (25/10/2026)

Trong **Simulation → Thiết lập → Mở khu vực nghiên cứu SAGSIN**, backend tạo khu vực riêng gồm 6 node, 7 link: ACCESS, RELAY, EDGE, UAV, tàu và vệ tinh snapshot 550 km. Chỉ ACCESS tiếp nhận thiết bị, chỉ EDGE đặt dịch vụ; tầm truy cập điện thoại 5 km tách khỏi backbone. Vùng nghiên cứu 100 km không đồng nghĩa toàn vùng có phủ sóng. Không tự sinh đường nối hay điều động node để ép mọi điểm có tuyến.

Chọn sự kiện, thời lượng và thời hạn chờ, rồi dùng **Thử sự kiện gần trạm trong vùng đã học**. Có 5 chế độ: bình thường, nghẽn mặt đất, đứt mặt đất, dự phòng tàu–vệ tinh, mất toàn bộ backhaul. Phiên đang truyền giữ băng thông; mất tuyến chờ và thử lại; hoàn tất/hết hạn giải phóng. **Chạy đồng hồ / Tiến 10 giây** điều khiển thời gian chung ở backend; UI cập nhật mỗi 2 giây. Chạy backend một worker; đồng hồ dừng khi pause hoặc server tắt. Vệ tinh nghiên cứu giữ snapshot, chưa mô phỏng quỹ đạo, RF hay gói tin thực.

Huấn luyện trong khu vực dùng `next_tick_application_link_delay_ms`: input telemetry link/payload tại t, nhãn cùng link/payload tại t+1. Nhãn tương lai chỉ dùng đánh giá sau quyết định. FL FedAvg học trên dữ liệu từng client; mục tiêu này không chấm RTT upload model hoặc chọn client. Chi phí trao đổi model tính riêng. Model học backbone hiện được suy luận cả cho tiếp cận UE, chưa có dữ liệu đo truy cập riêng. Dataset cũ giữ mục tiêu RTT FL để tái lập thí nghiệm trước. Việc app lưu dữ liệu từng client tập trung phục vụ mô phỏng/audit, chưa là triển khai FL phân tán thực tế.

Demo MySQL: scenario **#7**, experiment **#6**, **6 client × (2.000 lịch sử + 20 online)**, 20 vòng, 2 local epoch. Tổng **12.120 mẫu**: train 7.200, validation 2.400, test 2.400, online 120. MAE **0,130392 ms**, persistence **0,129412 ms**: FL chưa tốt hơn baseline. Năm ca điều kiện mạng đã đối chiếu cùng trạng thái; các ca có tuyến đều chọn cùng đường, mất toàn bộ backhaul trả `no_path`. Chưa có bằng chứng FL cải thiện định tuyến.

Mở `data/output/exports/regional_research/report.html` để xem báo cáo, JSON/CSV và ảnh UI. Toàn bộ 107 kiểm thử đã qua; 3 kiểm thử khu vực chạy lại sau dọn mã. Code mới tách telemetry, dataset link, khu vực, vòng đời và đánh giá; formatter không phải dependency runtime. Các mô tả RTT/giữ băng thông đến khi xóa phía dưới áp dụng luồng cũ ngoài khu vực nghiên cứu.

## Chạy ứng dụng chính

Từ thư mục gốc project, với môi trường Python đã cài `requirements.txt` và database đang chạy:

```powershell
uvicorn backend.main:app --reload
```

Mở `http://127.0.0.1:8000`, chọn **FL Training**. Tác vụ mặc định là Network delay prediction. Có thể chạy riêng từng policy hoặc so sánh Random/FedAvg, static Delay-Aware và prediction-aware trên cùng dataset. **Results** có dữ liệu thô theo client, prediction audit, metric, checkpoint inference và CSV.

`DATABASE_URL` lấy từ biến môi trường hoặc `.env`; mặc định là `mysql+pymysql://root:@localhost:3306/SAGSINs_db`. Backend tự tạo bảng còn thiếu và áp dụng migration dữ liệu có phiên bản khi khởi động, giữ nguyên dữ liệu đang có. Dữ liệu mạng thô được sinh từ snapshot node/link khi tạo experiment; có thể tái sử dụng dataset đã lưu.

### Đồng bộ database sau khi pull

Teammate bật MySQL (XAMPP ở ổ C vẫn dùng bình thường), cấu hình `DATABASE_URL` tới database của mình rồi chạy lệnh như cũ:

```powershell
git pull
uvicorn backend.main:app --reload
```

Database MySQL cần tồn tại trước khi chạy; nếu máy mới chưa có, tạo database `SAGSINs_db` (hoặc tên đã đặt trong `DATABASE_URL`). Backend tự tạo bảng và thêm dữ liệu, không cần import file SQL của người khác.

Migration `20261023_01_global_polar_coverage` bổ sung **72 vệ tinh quỹ đạo cực ở 1.200 km**, giữ nguyên 24 vệ tinh ban đầu: **96 vệ tinh, tổng 178 node** trong scenario mặc định. Nếu database chưa có scenario mặc định, backend khởi tạo bộ 106 node gốc rồi bổ sung 72 vệ tinh. Tên scenario cũ có hậu tố `106` được giữ để bảo toàn tham chiếu; số lượng hiển thị lấy từ database.

Lịch sử nằm trong bảng `database_migrations`. Mỗi phiên bản chỉ áp dụng một lần, có transaction và kiểm tra ID; khởi động lại không thêm trùng, không ghi đè chỉnh sửa hoặc phục hồi node đã chủ động xóa. Node/link, experiment, dataset và checkpoint cũ được giữ nguyên. `python -m backend.database.seed_db` cũng dùng quy trình bổ sung an toàn này, không còn reset dữ liệu.

Migration tiếp theo `20261023_02_feasible_snapshot_links` tạo topology khả thi cho snapshot vị trí: bốn lân cận gần nhất mỗi node và cây khung trên các cặp thỏa tầm nhìn/giới hạn khoảng cách. Không tự tạo backbone GROUND–GROUND mới. Link radio ACTIVE cũ vi phạm điều kiện được chuyển INACTIVE và ghi ID trong lịch sử migration, không xóa bản ghi; link đã chủ động tắt không được tự bật lại. Bộ sinh link lân cận trên giao diện cũng kiểm tra tầm nhìn. Khả thi ở snapshot không đồng nghĩa với liên kết luôn tồn tại khi vệ tinh chạy theo quỹ đạo.

Phải commit/push cả code migration và `data/input/global_ground_nodes/polar_coverage_satellites_v1.csv` để teammate nhận được khi pull. Không đưa `.env`, database cá nhân hay backup SQL lên Git. Không sửa inventory của một phiên bản đã áp dụng; các lần bổ sung sau cần migration có phiên bản mới.

Chi tiết cấu hình và kiểm tra phủ sóng nằm trong README này. Phủ sóng ở đây là hình học trong mô hình quỹ đạo tròn lý tưởng, không phải cam kết dung lượng hoặc SLA. Dataset/checkpoint cũ không bị huấn luyện lại; tạo experiment mới nếu cần dữ liệu huấn luyện cho topology đã mở rộng.

Chức năng chính đều thuộc `backend.main:app`. `backend.network_demo` chỉ là tiện ích thử bằng database SQLite riêng.


## Bắt đầu lại dữ liệu huấn luyện

`python -m backend.reset_training --database main` chỉ kiểm tra số bản ghi.
Thêm `--apply` để sao lưu vào `data/output/training_reset_backups/` rồi xóa experiment,
round, metric, prediction, checkpoint và dataset mạng đã sinh. Dùng
`--database demo` cho SQLite demo. Scenario, node, link và cấu hình participant
được giữ lại; dataset_size/selected của participant được đưa về 0/false.
Công cụ từ chối reset khi có job QUEUED/RUNNING. ID bản ghi không bị đánh lại.

UI Simulation mặc định bật tự huấn luyện khi thiếu checkpoint; có thể tắt trong thiết lập nâng cao. API tích hợp vẫn phải gửi `auto_train: true` nếu cần tự huấn luyện.
Điểm xa dùng điều động vệ tinh/UAV/tàu (snapshot mô phỏng) khi bật `allow_reposition: true`; FL chấm RTT tuyến, ETA tính bằng tốc độ/khoảng cách. Xem mục định tuyến sự kiện bên dưới.
Không chạy `backend.network_demo` chỉ để mở dữ liệu trống: tiện ích này tạo
comparison mới mỗi lần chạy; dùng `backend.main:app` với DATABASE_URL phù hợp.


## Vai trò các màn hình

| Màn hình | Chức năng |
|---|---|
| Simulation | Địa cầu, đặt sự kiện, liên kết nền và phân tích tuyến |
| Dashboard | Tổng quan node/link, participant và experiment từ database |
| Network | Quản lý node, link, trạng thái, lọc và xuất CSV |
| Participants | Chọn pool client ACTIVE và cấu hình local epochs |
| FL Training | Tạo/chạy experiment hoặc so sánh các scheduler |
| Experiments | Lịch sử, trạng thái và cấu hình từng lần chạy |
| Results | Metric theo round/client, raw data, decision audit và checkpoint inference |

Sidebar ở bên trái; địa cầu phủ toàn bộ vùng nội dung Simulation với thanh điều khiển nổi. Thiết lập và Phân tích tuyến mở thành bảng nổi bên phải trên desktop hoặc bảng phía dưới trên mobile, không thu nhỏ địa cầu. Mô phỏng tấn công và nút chuyển 2D/3D chưa hoạt động đã được gỡ. Các trang dùng dữ liệu API; metric chưa có được ghi là chưa có, không dựng số liệu giả ở frontend.

## Kết quả cập nhật ngày 23/10/2026

Trên database MySQL cục bộ, experiment **#2**, dataset **#2**, FL Predictive đã **COMPLETED 30/30 vòng**. Cấu hình: pool 178 client, chọn 24 client/vòng, 320 mẫu lịch sử/client, thêm 100 online tick/client, Non-IID, seed 42, normal profile, 2 local epochs, learning rate 0,01, batch size 64, dropout 0, timeout 120.000 ms. Mỗi vòng chỉ huấn luyện các client được chọn; pool 178 không có nghĩa mọi client đều được chọn ở mỗi vòng.

Dataset có **74.760 observation**, đủ 72 vệ tinh bổ sung; cả 178 profile dùng link đại diện đã lưu. Checkpoint vòng 30 có **MAE test 4,27085 ms**, validation MAE 4,22933 ms; persistence test MAE 4,27618 ms. Chênh lệch với persistence rất nhỏ, chưa đủ kết luận lợi ích tổng quát. Không đối chiếu trực tiếp MAE với model #1 như thí nghiệm cùng điều kiện vì hai dataset khác nhau.

Database có **487 link: 460 ACTIVE, 27 INACTIVE**. Đã thêm 407 link, tắt 27 link không khả thi, không xóa lịch sử. Toàn bộ 178 node thuộc một thành phần liên thông; tất cả link ACTIVE qua kiểm tra điều kiện snapshot. API tự chọn model #2 khi không chỉ định experiment. Gaming tại 49 tọa độ, gồm vùng cực và đại dương, đều có tuyến ở chế độ **configured** (chỉ dùng link đã lưu), không cần link ước tính hoặc điều động vệ tinh. Ví dụ Nam Thái Bình Dương: `SAT-POLAR-020 → SAT-023 → GND-AUS-001`.

ID experiment/dataset/scenario là của máy hiện tại; database mới trên máy teammate có thể cấp ID khác. Migration đồng bộ topology, không sao chép model hoặc dữ liệu huấn luyện cá nhân qua Git. Để tạo model mới trên máy khác, chọn scenario trong FL Training và nhập cấu hình tương ứng. Model cũ và dataset cũ được giữ nguyên.

Xem kết quả cục bộ tại `/results.html?experiment_id=2`. Báo cáo JSON chi tiết trong `data/output/database_backups/training-topology-20261023-result.json` được bỏ qua bởi Git.

## Thời gian và chuyển động mô phỏng

### Form và theo dõi FL trực tiếp (25/10/2026)

FL Training chia thành Dữ liệu, Quy mô huấn luyện và Thiết lập nâng cao. Bảng dự toán gọi API read-only `POST /api/fl/preview`: phân biệt toàn dataset với candidate pool, đọc số mẫu thực tế của dataset cũ (kể cả split tùy biến), hiển thị train/validation/online/test, khoảng số mẫu vòng đầu, cấu hình epochs riêng, 12 đầu vào → 1 đầu ra và model 961 tham số / 3.844 byte. Chọn dataset cũ khóa seed/profile/partition/samples/online theo metadata, không sửa dữ liệu đã lưu.

Đã bỏ trần cố định 50 client, 100 vòng, 2.000 mẫu/client, 20 epochs (cả Participants), batch 512, LR 1 và timeout 120 giây. Client/vòng bị giới hạn bởi pool ACTIVE hợp lệ; số mẫu lịch sử tối thiểu vẫn 40; epochs/batch/vòng/timeout là số nguyên dương; LR dương hữu hạn; dropout trong [0,1], seed trong [0,2147483647]. Dropout=1 là cấu hình kiểm thử mọi client thất bại. `online_steps` mặc định 100, cấu hình được trong form/API; dataset mới phải có online_steps >= rounds, dataset cũ kiểm tra số online observation thực tế từng candidate trước khi xếp hàng. CLI tạo dataset và benchmark hỗ trợ `--online-steps`. Nhiều mẫu/epochs hơn không bảo đảm MAE tốt hơn.

Worker lưu snapshot `training_progress` trong config experiment ở từng ranh giới chọn client, bắt đầu/kết thúc local training, tổng hợp, hoàn tất vòng và kết thúc experiment. API `GET /api/fl/experiments/{id}/progress` đọc trạng thái mới nhất; `/events` gửi SSE snapshot và heartbeat, kết nối lại luôn lấy snapshot hiện tại, không cam kết replay mọi sự kiện trung gian. Log gần nhất giữ tối đa 40 sự kiện; audit từng vòng vẫn nằm trong các bảng kết quả. Trình duyệt có polling dự phòng khi SSE gián đoạn, khôi phục experiment/comparison sau reload và chặn phản hồi cũ ghi đè màn hình của lần chạy mới. Progress tồn tại qua restart; job dở dang vẫn chưa tự resume.

Simulation phát hiện run trong scenario, tô sáng client đang chọn/học/hoàn tất/lỗi và vẽ trao đổi với bộ tổng hợp **logic** minh họa. Đường FL không phải link vật lý, không biểu diễn đo gói tin hoặc chứng minh mô hình client phân tán. Chuyển động tuyến/packet có giảm hoạt ảnh theo prefers-reduced-motion. Khi network_delay experiment hoàn tất, danh sách checkpoint trong routing tự cập nhật; không tự tính lại tuyến hay thay cấu hình của các điểm cũ. Topology vẫn theo snapshot, chưa thêm liên kết động/quỹ đạo/handover.

Hoạt ảnh điều động phát ở mức cố định 20×; không nhân tốc độ vật lý và không phải đồng hồ thời gian chung cho toàn mạng. Nút Tốc độ xoay điều chỉnh cách quan sát địa cầu; mức 1× quay một vòng trong 6 phút (bằng mức 5× trước đây). Phân tích tuyến mở danh sách các điểm của scenario hiện tại; chọn điểm để xem chi tiết và nhấn Trở về danh sách tuyến để chọn tuyến khác. Nhấn trực tiếp điểm sự kiện trên địa cầu cũng mở thông tin và tuyến của điểm, kể cả điểm chưa có tuyến. Nhấn thiết bị mở bảng thông tin tài nguyên; vệ tinh hiện thêm quỹ đạo minh họa. Esc, nút đóng hoặc nhấn ra ngoài sẽ ẩn thông tin và quỹ đạo; hover chỉ đổi con trỏ.

Muốn mô phỏng định tuyến liên tục phải nối một đồng hồ chung với bộ lan truyền quỹ đạo, cập nhật vùng phủ/topology theo thời điểm, dự đoán thời gian tồn tại liên kết và handover. Vệ tinh không được coi là phương tiện tự đổi hướng tới điểm sự kiện. Bộ điều động SPACE theo cung cầu hiện còn là thử nghiệm đơn giản hóa; chòm vệ tinh mới đã có vùng phủ trong cấu hình được kiểm tra nên không cần dùng bộ này ở 49 ca nêu trên. Hướng vật lý phù hợp là giữ quỹ đạo vệ tinh và điều động UAV/tàu theo giới hạn hoạt động, hoặc chờ cửa sổ phủ sóng.

## Dữ liệu mạng và huấn luyện FL

### Dữ liệu và mô hình

- Dữ liệu generated có seed, generator version, snapshot topology/profile và SHA-256 fingerprint.
- Link ACTIVE liên quan đến node được dùng làm link đại diện, với bandwidth bị giới hạn bởi node/link, latency có sàn propagation theo khoảng cách RF. Khi không có link phù hợp, dataset ghi rõ `synthetic_client_server_channel`; không suy ra route từ vị trí địa lý.
- SEA hiện biểu diễn thiết bị dùng RF trên biển; không áp dụng tốc độ RF cho mô hình âm học dưới nước.
- Congestion là chuỗi theo thời gian có tương quan, làm thay đổi latency/bandwidth/loss. Công thức round-trip: `2 * latency_ms + 2 * payload_mb * 8 * 1000 / bandwidth_mbps`, điều chỉnh tổn thất truyền lại theo `1 / (1 - loss)`.
- Input chỉ gồm thông số hiện tại: delay, latency, bandwidth, distance, load, loss, jitter, payload và layer. Target là round-trip communication delay của model ở tick tiếp theo. Payload khớp số byte tensor FP32 của regressor; chưa gồm header/protocol overhead.
- Predictor là MLP nhỏ, dự đoán phần hiệu chỉnh trên `log1p(current_delay)`. Ban đầu correction bằng 0 nên predictor tương ứng persistence baseline. Không có cam kết FL luôn tốt hơn baseline; MAE/RMSE/R² và baseline được lưu để đánh giá điều này.
- IID dùng profile trung bình chung; Non-IID dùng profile từng client. Các chuỗi vẫn có seed riêng theo client.
- Chia theo thứ tự: 60% historical train, 20% validation, 100 online ticks, 20% future test. Giữa các split có gap để target t+1 không tràn sang split kế tiếp.
- Chỉ completed client bổ sung observation của tick vừa hoàn tất vào lịch sử local, sau khi train/selection/outcome đã xong. Validation/test không tham gia local training. Tập test luôn nằm sau toàn bộ online ticks.

### Scheduling và kết quả

- FedAvg: chọn đều ngẫu nhiên có seed.
- DelayAware: chọn theo công thức communication từ profile tĩnh đã snapshot.
- Predictive: round 1 dùng cùng random policy để khởi động; từ round 2 dùng global model của round trước, chỉ đọc current features. Sắp xếp dự đoán tăng dần, hòa điểm theo client ID.
- Dataset trace được cố định để comparison dùng cùng môi trường ngoại sinh. Lựa chọn scheduler làm thay đổi client updates và lịch sử local được bổ sung; chưa mô hình hóa tác động ngược của lựa chọn lên tắc nghẽn toàn mạng.
- Client training thực sự chạy bằng PyTorch trên host backend. Client partitions được phân vùng logic trong DB chung; chưa phải tiến trình/thiết bị cô lập hay bảo đảm Differential Privacy.
- Thời gian training được đo trên host; thời gian communication/round song song và energy 10 W là ước tính. Host CPU duration có thể khác giữa các lần chạy dù predictions/samples/seed được tái lập.
- Local loss/global loss là MSE của `log1p(delay)`, không phải ms². MAE/RMSE là ms. Regression không có classification accuracy; API trả `accuracy: null`.
- Mỗi round lưu checkpoint JSON, MAE/RMSE/R², validation MAE, persistence test MAE, số test samples và policy source. Decision audit có observation ID, model round, dự đoán, rule estimate và selected flag; outcome kế tiếp chỉ hiện cho selected clients.
- Checkpoint dùng lại được sau restart để inference; unfinished experiments chưa tự resume.

Trang Results xem dữ liệu thô, predicted-vs-observed, audit từng client, so sánh policy và xuất CSV. Có nút dự đoán một sample bằng checkpoint đã lưu mà không train lại.

### API chính

| API | Mục đích |
|---|---|
| `POST /api/fl/datasets` | Seed dataset snapshot mới |
| `GET /api/fl/datasets?scenario_id=1` | Danh sách, provenance và split counts |
| `GET /api/fl/datasets/{id}` | Snapshot/config dataset |
| `GET /api/fl/datasets/{id}/observations?client_id=...&split=train&limit=20&offset=0` | Kiểm tra local partition |
| `POST /api/fl/experiments` | Chạy network_delay hoặc MNIST |
| `POST /api/fl/comparisons` | So sánh 3 policy cho network_delay, 2 cho MNIST |
| `GET /api/fl/experiments/{id}` | Metric, outcomes, predictions qua các rounds |
| `POST /api/fl/experiments/{id}/predict` | Inference với checkpoint mới nhất đã lưu |

Ví dụ request experiment:

```json
{
  "task": "network_delay", "scenario_id": 1,
  "algorithm": "Predictive", "rounds": 10, "client_count": 5,
  "samples_per_client": 160, "partition": "non_iid",
  "seed": 42, "learning_rate": 0.01, "local_epochs": 1,
  "batch_size": 64, "network_profile": "normal",
  "dropout_probability": 0, "timeout_ms": 30000
}
```

Để reuse, thêm `dataset_id`; scenario/seed/partition/network_profile phải khớp dataset. Comparison nhận cùng request nhưng bỏ `algorithm`. Khi thiếu task, API vẫn mặc định MNIST để tương thích các caller cũ; giao diện gửi rõ `network_delay`.


## Định tuyến sự kiện dựa trên model FL

Màn hình Simulation dùng `POST /api/routing/events` để lưu điểm và chọn tuyến trên server. `GET /api/routing/events` khôi phục điểm cùng kết quả, cấu hình và tiến độ điều động; `PUT /api/routing/events/{id}` tính lại, `DELETE /api/routing/events/{id}` xóa điểm và giải phóng băng thông. `POST /api/routing/event` vẫn hỗ trợ tính thử mà không lưu hoặc giữ thêm tài nguyên. `GET /api/routing/context` cung cấp scenario và checkpoint FL có thể dùng.

Điểm chưa xóa được lưu trong bảng `routing_events`, giữ qua tải lại trang và khởi động lại backend. Backend tự tạo bảng bổ sung khi khởi động; không reset dữ liệu cũ. Khi gửi lại cùng `client_key`, API trả điểm đã lưu để tránh tạo trùng do thử lại kết nối. Những điểm chỉ tồn tại trong bộ nhớ trình duyệt trước khi cập nhật này không thể khôi phục sau khi trang cũ đã đóng.

Trong Phân tích tuyến, mỗi mục danh sách và màn hình chi tiết có nút **Xóa điểm**. Nút **Xóa tất cả điểm** xóa các điểm thuộc scenario đang xem và giải phóng băng thông của chúng. Số hiển thị (`display_number`) được lưu riêng với ID database; khi scenario không còn điểm, điểm mới bắt đầu lại từ **Điểm 1**, giữ tên sau tải lại. Xóa một điểm không đánh số lại các điểm còn tồn tại. Migration tự thêm số hiển thị cho bảng cũ, giữ nguyên ID và dữ liệu; không reset bộ đếm ID database.

Với database đã có bảng `routing_events` từ phiên bản chưa có `client_key`, startup tự thêm cột, cấp mã cho các bản ghi cũ và bổ sung ràng buộc duy nhất. `create_all` chỉ tạo bảng còn thiếu nên cần bước migration này; nếu thiếu, cả tải danh sách và lưu điểm sẽ lỗi HTTP 500 trước khi tính tuyến. Migration giữ nguyên ID, tọa độ, cấu hình, kết quả và tiến độ đã lưu, chạy lại không đổi mã.

Mỗi tuyến giữ nhu cầu Mbps của dịch vụ trên từng node đi qua (tính một lần mỗi node, không nhân đôi tại relay) và từng link hai chiều dùng chung. Băng thông còn lại = dung lượng sau hệ số profile/tải nền − tổng Mbps đã giữ của các điểm khác. Dijkstra xét phần còn lại này: dùng chung node nếu đủ và có tổng điểm tốt, chuyển sang node/tuyến khác nếu thiếu; không giành băng thông của điểm cũ. Giảm tải nền không xóa phần đã giữ. Các yêu cầu ghi được khóa theo scenario để kiểm tra và cấp tài nguyên trong cùng transaction. Điểm không có tuyến vẫn được lưu nhưng không giữ băng thông. Tính lại một điểm loại phần giữ của chính nó khỏi phép tính; các điểm khác vẫn giữ tài nguyên. Điểm chưa đủ băng thông không tự thử lại khi có tài nguyên trống; dùng Cập nhật mạng & tính lại.

Tuyến đang chờ điều động cũng giữ tài nguyên cho phương án đã chọn. Node đang di chuyển chưa nhận thêm luồng; khi tới nơi, các tuyến mới có thể dùng chung phần băng thông còn lại. Node đang phục vụ tuyến cũ không bị điều động đi nơi khác. Bảng phân tích cho biết Mbps đã cấp, phần đã dùng trước và phần còn sau khi cấp tại thời điểm quyết định. Tooltip node hiển thị số điểm đang dùng, Mbps đã giữ và dung lượng còn trước tải nền theo các điểm đã tải. Đây là cấp phát theo nhu cầu cố định trong mô phỏng, chưa mô phỏng hàng đợi hoặc tranh chấp từng gói tin.

### Điều động phương tiện và lớp liên kết nền

Giao diện hiện gửi `allow_reposition: true`, `mobility_boost: 2` và mặc định bật `auto_train`. API giữ `allow_reposition` và `auto_train` ở mặc định tắt để tương thích các client cũ. Đặt điểm không bị giới hạn tọa độ địa lý hợp lệ; tìm phương tiện toàn scenario không đồng nghĩa với kết nối thẳng vô hạn về GROUND.

Khi bật điều động, tiếp cận phải thỏa tầm nhìn và khoảng cách demo: GROUND 50 km, SEA 200 km, AIR 1.500 km, SPACE 5.000 km; với thiết bị có độ cao, đường chân trời thường giới hạn chặt hơn. Nếu nhập bán kính riêng, lấy ngưỡng nhỏ hơn. Nếu không có vùng phủ hoặc đường về GROUND, hệ thống xét các vị trí giao giữa vùng phủ sự kiện và backhaul mặt đất, so sánh vệ tinh/UAV/tàu; vùng xa hơn dùng chuỗi vệ tinh ACTIVE hiện có. Link cũ chạm phương tiện đã di chuyển được bỏ khỏi snapshot, rồi dựng lại topology để tránh giữ kết nối ở vị trí cũ. Không thay đổi vị trí/link trong database.

Tốc độ cơ sở demo: SPACE 7,5 km/s, AIR 0,07 km/s, SEA 0,015 km/s, nhân hệ số tăng tốc 1–5. `ETA = quãng đường cung cầu tại độ cao thiết bị / tốc độ`. Các phương tiện trong chuỗi đi đồng thời, thời gian chờ là ETA lớn nhất. Chọn trên tập vị trí ứng viên theo `ETA_seconds + route.cost / 1000`; RTT dự đoán, băng thông và khoảng cách góp vào `route.cost`. Đây là tìm kiếm ứng viên hữu hạn với gán vệ tinh tham lam, chưa chứng minh tối ưu toàn cục; các phương án khác nhau có thể cần số vệ tinh khác nhau.

FL chỉ dự đoán RTT kênh ở vị trí sau điều động, không dự đoán ETA hay quỹ đạo. Quỹ đạo chuyển tiếp là cung cầu giả lập, chưa xét động lực học quỹ đạo, nhiên liệu, tránh va chạm, đường hàng hải hay đất liền. Phần ước tính độ trễ ứng dụng là sau khi có kết nối; thời gian chờ điều động được hiển thị riêng. Không đảm bảo kết nối nếu thiếu phương tiện ACTIVE/băng thông/đích GROUND hoặc topology không cho backhaul; API trả nguyên nhân `mobility_unavailable` thay vì bịa đường truyền.

UI mở phân tích ngay khi thả điểm, hiển thị trạng thái huấn luyện/tính tuyến/điều động. Phương tiện di chuyển trên địa cầu theo thời gian mô phỏng với tốc độ phát cố định 20×, thanh tiến độ, tạm dừng và nút tua tới kết nối. Tiến độ được lưu định kỳ và khi hoàn tất. Chỉ vẽ tuyến truyền và chạy gói tin khi các phương tiện tới vị trí. Mọi điểm của scenario hiện tại hiển thị tuyến và gói tin đồng thời, dùng màu phân biệt. Chỉ tuyến đang xem chi tiết trong Phân tích tuyến được làm đậm; trở về danh sách hoặc đóng bảng đưa các tuyến về độ mờ nhẹ như nhau. Các tuyến dùng vị trí đã giữ thống nhất khi chia sẻ node.

`GET /api/routing/topology` cung cấp liên kết nền từ cùng hàm dựng topology với routing. Hiển thị tối đa ba link gần nhất mỗi node trước khi hợp nhất cặp để tránh rối; việc định tuyến vẫn xét toàn bộ link. Nét liền mờ: link ACTIVE đã lưu; nét đứt mờ: link ước tính. Đường nền, tuyến chọn, đối chứng và gói tin cập nhật theo vị trí marker mỗi khung hình, dùng lại buffer hình học. Node được điều động giữ vị trí theo phương án/tiến độ đã lưu; thiết bị khác tiếp tục chuyển động. Khi điều động, lớp nền được ẩn; khi tới nơi dùng tập link từ snapshot mới. Có thể tắt lớp này. Tuyến chọn và đường điều động dùng màu sáng hơn lớp nền. Đây là cập nhật hình vẽ: tập liên kết, số liệu và quyết định định tuyến vẫn theo snapshot gần nhất, chưa tự kiểm tra lại vùng phủ hay tính lại tuyến khi vệ tinh di chuyển.

### Khi đặt một điểm

1. Lấy node ACTIVE hợp lệ thuộc scenario đã chọn. Không đi qua node hoặc link của scenario khác.
2. Với client API cũ không bật `allow_reposition`, `access_radius_km: null` dùng tiếp cận ảo toàn scenario. Với UI bật điều động, áp dụng vùng phủ theo lớp như phần trên. Node mặt đất/biển dùng khoảng cách cung trên mặt cầu; tiếp cận xa là kênh ảo mô phỏng, không phải khẳng định phủ sóng vô tuyến. Node có độ cao dùng khoảng cách không gian và vẫn phải trên đường chân trời. Có thể nhập bán kính dương (tối đa 20.040 km) để giới hạn rõ ràng; bán kính này được giữ nguyên kể cả ở vùng xa, không tự mở rộng.
3. Đích mặc định là GROUND ACTIVE có tổng chi phí nhỏ nhất. Có thể giới hạn đích vào một GROUND cụ thể; điểm tiếp cận GROUND cũng có thể là đích để mô phỏng xử lý tại chỗ.
4. Topology mặc định `adaptive` giữ nguyên link ACTIVE đã lưu và bổ sung các link ước tính tạm thời có đường chân trời phù hợp. Giới hạn khoảng cách là 5000 km nếu có SPACE, 1500 km nếu có AIR, 500 km với các cặp còn lại; riêng GROUND-GROUND tối đa 20000 km là giả định backbone mặt đất. Link này chỉ tồn tại trong lượt định tuyến, không ghi vào database. Có thể chọn `configured` hoặc `estimated` để giới hạn nguồn link.
5. Đo khoảng cách mặt đất đến GROUND ACTIVE gần nhất. Khi xa hơn 500 km, dùng sở thích thiết bị theo dịch vụ như một penalty nhỏ, không loại bỏ hay ưu tiên tuyệt đối lớp nào. Xét chung mọi ingress và mọi đường về GROUND theo một hàm điểm có RTT tiếp cận, bandwidth ingress, RTT và bandwidth từng hop, khoảng cách từng chặng cùng penalty sở thích. Tạo trạng thái kênh từ profile và tải đã chọn. Nếu không có tuyến ở tải đó, trả `no_path`; chỉ tìm tải thấp hơn khi bật `allow_load_reduction` (mặc định tắt), và công khai tải yêu cầu/tải áp dụng.
6. Với chính sách Predictive, chọn checkpoint mới nhất của experiment FL **COMPLETED**, task `network_delay`, cùng scenario, có round đã aggregate, feature version và target phù hợp. Nếu chưa có model và không chọn experiment cụ thể, chỉ tự xếp hàng 10 vòng Predictive Network delay khi API gửi `auto_train: true`; mặc định trả `no_model` để người dùng chủ động huấn luyện trong FL Training. Tối thiểu cần hai client hợp lệ. Việc huấn luyện chỉ cung cấp model chấm hạng; nó không tự tạo kết nối.
7. Batch inference một lần cho mọi hướng truyền và chặng tiếp cận hợp lệ bằng `NetworkDelayRegressor` đã lưu. Dijkstra tìm tuyến tối ưu trên toàn bộ node ingress cùng lúc; chỉ số khoảng cách, băng thông và độ trễ quyết định chính, sở thích loại thiết bị là penalty phụ. Đường nét đứt biểu thị link ước tính. Kết quả nêu các chỉ số ingress và tổng điểm để giải thích lựa chọn.
8. Chạy Dijkstra theo công thức tĩnh trên cùng topology, tải, ingress, tập đích và ràng buộc băng thông. Hiển thị cả hai đường và dùng **cùng model** chấm hai tuyến để đối chiếu. Không khẳng định tuyến Predictive luôn có tổng RTT thấp hơn: mục tiêu còn gồm phạt băng thông.

### Chi phí và ràng buộc

`cost(path) = soft_event_penalty + Σ (tiếp cận + hops) [w_delay × RTT_proxy_ms + w_capacity × 100 / bandwidth_Mbps + w_distance × distance_km / 100]`

RTT tiếp cận được tính từ độ trễ node và khoảng cách sự kiện–node (`max(node_latency, distance/c)`), băng thông tiếp cận, payload FL và loss mô phỏng. RTT công thức từng hop là download/upload payload FL qua kênh đối xứng, điều chỉnh loss; RTT dự đoán lấy từ checkpoint cho cả tiếp cận lẫn từng hop, nên model vẫn quyết định được node tiếp cận khi tuyến không có hop backbone. Ingress và từng hop đều chịu phạt bandwidth **cộng theo chặng**, không chỉ dùng bottleneck; bottleneck được báo riêng. Sở thích lớp theo dịch vụ chỉ là penalty nhỏ (0–3 điểm) nên khoảng cách, băng thông và độ trễ có thể làm thay đổi lựa chọn. Khoảng cách là chi phí mềm, không phải rào cản bán kính mặc định. Mỗi chặng phải đủ `min_bandwidth`; có thể ghi đè bằng `required_bandwidth_mbps` dương. API trả `route.score_breakdown` tách điểm độ trễ, băng thông, khoảng cách, sở thích và tổng; tổng các thành phần bằng chi phí Dijkstra. Băng thông lớn làm giảm phạt nghịch đảo, khoảng cách xa làm tăng phạt tuyến tính, tất cả trọng số đều không âm.

| Dịch vụ | w_delay | w_capacity | w_distance | Băng thông tối thiểu (Mbps) |
|---|---:|---:|---:|---:|
| Message | 0.55 | 0.10 | 0.10 | 0.05 |
| Video Call | 0.45 | 0.40 | 0.20 | 2 |
| Watch Video | 0.20 | 0.75 | 0.15 | 5 |
| Gaming | 0.80 | 0.08 | 0.30 | 1 |
| Emergency | 1.00 | 0.15 | 0.10 | 0.10 |

Đây là chính sách mô phỏng của ứng dụng, không phải SLA hay chuẩn dịch vụ. Emergency ưu tiên độ trễ trong mục tiêu; mọi dịch vụ giữ Mbps theo cùng cơ chế và không giành lại phần đã cấp của điểm cũ. Chưa mô phỏng ưu tiên hàng đợi giữa các sự kiện.

Topology ước tính chọn tối đa hai hàng xóm mỗi node trước khi hợp nhất các cặp đối xứng. Giới hạn khoảng cách: có SPACE 5.000 km, có AIR 1.500 km, còn lại 500 km; node có độ cao phải thỏa điều kiện đường chân trời. Không thêm cầu nối để ép toàn mạng liên thông. Chế độ này không ghi database. Nút “Sinh & lưu link lân cận” là thao tác riêng, sử dụng API tạo link hiện có, giới hạn trong scenario đang chọn.

### Model thực sự dự đoán gì?

Checkpoint hiện được huấn luyện từ telemetry mô phỏng của từng client/kênh đại diện, target `next_tick_model_round_trip_ms`: RTT của **payload FL huấn luyện** ở tick tiếp theo. Dataset chưa được thiết kế và kiểm chứng như bộ đo độ trễ từng hop hay độ trễ ứng dụng đầu-cuối.

Vì vậy áp dụng model lên chặng tiếp cận và từng hop hiện là **chỉ số thay thế cho xếp hạng tuyến mang tính thực nghiệm**. API giữ tổng RTT hop riêng và bổ sung `total_predicted_transfer_ms`/`total_static_transfer_ms` gồm RTT tiếp cận theo cùng chính sách. `route.access_rtt_ms` giữ RTT công thức; `route.predicted_access_rtt_ms` là suy luận FL. UI ghi rõ cả hai và phần tiếp cận mô phỏng. Không gọi RTT payload FL là latency Video Call/Gaming. Load, jitter, loss và observed RTT đầu vào được dựng từ công thức, không được quảng bá là phép đo thời gian thực. Không đọc target tương lai, nhãn online/test hay prediction audit để quyết định tuyến.

Kết quả `route.application` tính riêng độ trễ ứng dụng một chiều theo store-and-forward: tổng latency kênh + tổng `payload_bytes × 8 / (bandwidth_Mbps × 1000)` ms, gồm ingress và các hop. Payload/ngân sách demo khai báo tại `APPLICATION_PROFILES`; băng thông đầu vào là phần còn lại khi cấp tuyến sau các luồng đã giữ, chưa phải độ trễ đo thực tế hoặc mô phỏng hàng đợi từng gói tin. Có tuyến chưa có nghĩa đạt ngân sách độ trễ. UI hiển thị trạng thái này và hỗ trợ xuất cấu hình/kết quả JSON. Các giới hạn chưa được kiểm chứng được nêu trong mục Phạm vi và hướng hoàn thiện của README này.

Để kiểm chứng tối ưu độ trễ ứng dụng đầu-cuối cần thu thập/sinh dataset theo từng link ở t và t+1, nhiều payload ứng dụng, trạng thái hàng đợi, lịch sử tải theo link và đo end-to-end. Sau đó huấn luyện/đánh giá model với target phù hợp, so sánh trên cùng điều kiện và dữ liệu giữ lại. Phiên bản này chưa triển khai DRL/QR-DQN.

### Sử dụng và kiểm tra

- Mở Simulation → chọn scenario → Dự đoán bằng model FL → chọn checkpoint hoàn tất hoặc tự chọn mới nhất → chọn sự kiện → nhấn trên địa cầu. Thiếu checkpoint sẽ tự huấn luyện nếu bật tùy chọn; có thể tắt hoặc chọn công thức tĩnh. Có thể nhập tọa độ bằng bàn phím trong cấu hình mở rộng; mặc định tìm trên toàn scenario và có thể nhập nhu cầu băng thông riêng. Sidebar luôn dọc bên trái; phần mô phỏng tấn công đã được gỡ.
- Thay đổi cấu hình chỉ áp dụng cho điểm mới. “Cập nhật mạng & tính lại” hủy chuyển động cũ và áp dụng cấu hình hiện tại cho toàn bộ điểm, tải lại node/link/model, bỏ tuyến cũ nếu cập nhật thất bại.
- Bảng phân tích có từng hop, tuyến công thức, nguồn dữ liệu và hoạt ảnh truyền minh họa 5 giây/lượt. Đường và gói tin bám thiết bị đang di chuyển; không thể suy ra routing liên tục theo quỹ đạo từ hoạt ảnh này.
- Kéo địa cầu không tạo sự kiện; Esc hủy chế độ đặt điểm; xóa điểm cũng giải phóng geometry/material. Request cũ không được ghi đè kết quả sau khi tính lại hoặc xóa điểm.

Chạy `.venv/Scripts/python.exe -m unittest discover -s tests -p test_routing.py -v`. Kiểm thử dùng SQLite riêng, bao gồm checkpoint PyTorch thật, huấn luyện FL rồi gọi routing và đối chiếu inference, đường và ingress thay đổi theo prediction, đặt điểm ở vùng cực/kinh tuyến 180°, chấm điểm khoảng cách/băng thông, nhu cầu riêng, tổng điểm thành phần, mất kết nối, bán kính tùy chọn, node OFFLINE và cách ly scenario.

`tests.test_saved_routing` kiểm tra khôi phục điểm, dùng chung node/link, chuyển ingress khi hết dung lượng, xóa và tính lại để giải phóng tài nguyên, thử lại không tạo trùng, lưu tiến độ điều động, giữ vị trí node dùng chung sau khi xóa điểm gốc, transaction huấn luyện và hai yêu cầu cấp phát đồng thời. Bộ `tests.test_saved_routing tests.test_routing tests.test_topology tests.test_database_migrations` đạt 56 kiểm thử. Kiểm tra trình duyệt với API và SQLite riêng xác nhận ba luồng truyền chạy đồng thời, làm đậm khi xem chi tiết, mờ nhẹ khi thoát, tải lại/khôi phục, xóa điểm, mobile và reduced motion.

## Polar coverage shell v1

The additive migration `20261023_01_global_polar_coverage` adds the committed
`data/input/global_ground_nodes/polar_coverage_satellites_v1.csv` inventory to the existing scenario. IDs are
`SAT-POLAR-001` through `SAT-POLAR-072`. The original 106 nodes remain unchanged:
50 GROUND + 20 SEA + 12 AIR + 24 original SPACE + 72 polar SPACE = 178 nodes.
The historical scenario name `SAGSIN-Global-Multilayer-106` is retained.

### Design and scope

The new shell uses 6 distinct polar planes, 12 uniformly spaced satellites in
each plane, 90-degree inclination and 1,200 km altitude. RAAN is 0, 30, 60, 90,
120 and 150 degrees; polar planes already extend over both hemispheres. Adjacent
planes have half-slot phase staggering. Explicit RAAN is stored as
`orbit_raan_deg`; phase and Earth-fixed initial coordinates share epoch
`2026-10-11T00:00:00Z`. Each node has simulated 100 Mbps bandwidth and 25 ms
latency. These are scenario assumptions, not a measured or deployed system.

This is a sufficient configuration, not a claim of the smallest constellation.
For any location the perpendicular distance to a plane is at most 15 degrees.
On that plane the nearest satellite is at most 15 degrees along-track away at
any time. A right spherical triangle gives a maximum nearest-satellite angular
distance of `acos(cos(15 degrees) * cos(15 degrees)) = 21.0906 degrees`.
At this altitude the corresponding minimum best elevation is 14.2685 degrees,
above the design threshold of 10 degrees. The bound assumes every new satellite
is available, circular polar orbits, constant altitude and a spherical Earth.
Atmospheric drag, J2, terrain, antenna beams and radio link budgets are excluded.

The supplemental 24-hour test samples a 5-degree global grid every 300 seconds:
769,896 point/time samples, zero gaps below 10 degrees. Results are committed in
`data/output/global_ground_nodes/polar_coverage_v1_validation.json`. The continuous geometric claim comes from
the analytical bound, not only from this discrete sample. Disabling satellites
or changing their orbits invalidates that claim.

This verifies access coverage. A route still needs sufficient bandwidth and
backhaul to an ACTIVE GROUND node. Routing currently uses database snapshots;
this upgrade does not implement continuous orbit propagation/handover in the
backend or establish an application-latency guarantee. The legacy experimental
SPACE repositioning planner is not an orbital maneuver model. The new shell
provides coverage without needing that planner in the tested global scenario.

### Reproduce and deploy

```powershell
python -m backend.database.global_coverage --check
python -m unittest discover -s tests -p test_database_migrations.py -v
```

`--write` regenerates the deterministic CSV. Once a migration has been applied,
keep its code/manifest immutable; publish a new version for a changed design.
Checksums use parsed values to tolerate Git LF/CRLF conversion across machines.

Normal backend startup applies the migration before accepting API requests:

```powershell
uvicorn backend.main:app --reload
```

Existing rows are not deleted or overwritten. The migration updates scenario
counts, records its version/checksum/details in `database_migrations`, and uses
a transaction. ID conflicts fail startup with an explanation and roll back the
data changes. MySQL uses a named lock to serialize the data upgrade. A fresh
database gets the original committed inventory followed by the polar shell.
An already-applied migration is not replayed when someone edits or deletes a
node. Other scenarios and historical FL datasets/checkpoints are preserved.
The database itself must already exist and the configured account must be able
to create tables, add the optional metadata column, and insert inventory rows.

No XAMPP configuration changes are needed. Local SQL backups belong in ignored
`data/output/database_backups/`, not in Git. Commit the migration code, CSV, validation
report and documentation so teammates receive the same upgrade via pull.

### Feasible stored links

The follow-up migration `20261023_02_feasible_snapshot_links` adds four nearest
eligible neighbors per node and a spanning forest over eligible pairs, preserving
existing active terrestrial backbone. New GROUND-GROUND fibre is not inferred.
Elevated links must meet the geometric horizon and 5,000 km (SPACE) / 1,500 km
(AIR) distance limits. Other surface channels retain the project's abstract
500 km limit; antenna heights/link budgets are not modeled. New link capacity
is the smaller endpoint capacity, and latency is at least endpoint latency
and distance/c. This is a database-position snapshot, not continuous orbital
contact planning. Infeasible existing active links are marked INACTIVE, not
deleted; previously inactive links are not reactivated. Migration details
record created/deactivated IDs, component membership and link-layer counts.

On the default 178-node snapshot this adds 407 links and deactivates 27 old
links: 460 ACTIVE links, 27 INACTIVE links, one connected component. Newly
created pairs include 147 SPACE-SPACE, 143 GROUND-SPACE, 74 SEA-SPACE and 43
AIR-SPACE. New FL datasets can use these stored incident links; existing
datasets/checkpoints retain their original immutable snapshots.


## Inventory gốc và quy ước tọa độ

Inventory gốc nằm ở `data/input/global_ground_nodes/global_multilayer_nodes_106.csv`; không sửa file để ghi đè database đã migration. Ground (50 node) giữ metadata quốc gia/thành phố đại diện, phân bố theo diện tích đất với điều chỉnh nhẹ từ GDP/ITU IDI, tối đa hai node/quốc gia. SEA (20 node) lấy waypoint hành lang hàng hải; AIR (12 node) là UAV ở 0,3 km; các vị trí là giả lập, không phải AIS, flight tracking hoặc trạm thực. Không suy diễn quốc tịch tàu từ waypoint trên biển.

24 vệ tinh gốc ở 550 km, độ nghiêng 53°, 6 mặt phẳng × 4 vệ tinh, Walker-style F=1. 72 vệ tinh quỹ đạo cực bổ sung có cấu hình được giải thích ở mục Polar coverage shell v1. Dữ liệu ngoài mặt đất có cờ `is_simulated=true`; độ cao database tính bằng km. Các giá trị demo: GROUND 100 Mbps/10 ms, SEA 25 Mbps/80 ms, AIR 50 Mbps/30 ms, SPACE 100 Mbps/25 ms.

Tọa độ WGS84 chuyển sang Three.js theo `x=r*cos(lat)*cos(lng)`, `y=r*sin(lat)`, `z=-r*cos(lat)*sin(lng)`, bán kính địa cầu 2. Renderer phóng đại độ cao để dễ quan sát, không thay đổi giá trị vật lý trong database. Initial satellite position được chuyển ECI sang Earth-fixed bằng GMST tại epoch `2026-10-11T00:00:00Z`. Trường `orbit_raan_deg` phân biệt hướng các mặt phẳng của shell cực.

Có thể tái tạo inventory gốc bằng `python -m backend.database.build_global_multilayer_inventory`; CSV bổ sung bằng `python -m backend.database.global_coverage --write`. Không sửa inventory/checksum của migration đã áp dụng; tạo phiên bản mới cho các lần thay đổi thiết kế.

## Nguồn dữ liệu và ghi nhận tác giả

### Ground data sources and attribution

- `country_area.csv` is a snapshot from [iliyaj/country-data](https://github.com/iliyaj/country-data),
  based on World Bank land-area values. World Bank defines land area in square
  kilometers excluding inland water: [AG.LND.TOTL.K2](https://data.worldbank.org/indicator/AG.LND.TOTL.K2).
- `geonames_country_info.csv` supplies continent codes and fallback area where
  the World Bank area snapshot has no entry. GeoNames data is CC BY 4.0:
  [countryInfo.txt](https://download.geonames.org/export/dump/countryInfo.txt).
- Country names, representative capital coordinates, population and GDP
  snapshots come from [iliyaj/country-data](https://github.com/iliyaj/country-data).
  Population and GDP are 2024 snapshots; GDP per capita is nominal GDP divided
  by population, not PPP-adjusted.
- `itu_idi_2025_scores.csv` captures the 2025 score table shown by
  [World Population Review](https://worldpopulationreview.com/country-rankings/ict-development-index-by-country),
  with [ITU](https://www.itu.int/itu-d/reports/statistics/idi2025/) as index
  publisher. Missing population/GDP values use the candidate-set median;
  missing ITU scores use 78 and are marked in the ground inventory.
- Capital and secondary-city locations are representative WGS84 proxies, not
  verified towers, cell sites, servers, vessels or devices.



## MNIST demo tùy chọn

Trong FL Training chọn **MNIST classification demo**. Dữ liệu tải vào `data/input/mnist`; lần đầu cần mạng để tải dataset. CNN nhỏ hỗ trợ Centralized, FedAvg và DelayAware; IID chia ngẫu nhiên theo seed, Non-IID dùng label-sorted shards. MNIST test set chỉ dùng đánh giá accuracy/loss. Bắt đầu với 2–3 vòng và 2–5 client để kiểm tra CPU. Huấn luyện chạy trên host backend; thời gian truyền, dropout/timeout và năng lượng là ước tính. Khác network-delay checkpoint, trọng số MNIST của runtime hiện tại không được lưu để resume sau restart.

## Benchmark và kết quả lịch sử

CLI so sánh nhiều seed/profile/distribution:

```powershell
python -m backend.network_benchmark --demo --scenario-id 1 --seeds 11 42 71 --profiles normal high_latency low_bandwidth --partitions iid non_iid --client-counts 5 10 --rounds 10
```

Mỗi comparison dùng cùng dataset/seed/candidate pool/cấu hình, chỉ khác chính sách chọn client. Artifacts gồm `experiments.json`, `runs.csv`, `aggregates.csv` trong `data/output/network_benchmarks/<timestamp>` (bỏ qua Git). Bỏ `--demo` để dùng database đang cấu hình; kiểm tra scenario ID trước khi chạy.

Lần khảo sát trước trên demo 106 node: 3 seed (11, 42, 71), 80 mẫu lịch sử/client, 5 client/vòng, 5 vòng, 2 local epochs, LR 0,01, Non-IID, dropout 0, timeout 30.000 ms; 27 experiment. Tổng cost truyền (client chậm nhất mỗi round), trung bình ba seed, là số liệu simulator:

| Profile | Random (ms) | Static DelayAware (ms) | Predictive (ms) |
|---|---:|---:|---:|
| Normal | 748,03 | 240,14 | 242,55 |
| High latency | 6.951,21 | 1.574,59 | 2.212,59 |
| Low bandwidth | 843,88 | 283,43 | 285,16 |

Ở khảo sát đó Predictive tốt hơn random nhưng chưa tốt hơn static về tổng cost; round đầu phải warm up bằng random. Đây là kết quả lịch sử trên cấu hình khác, không phải kết quả model #2 hoặc bằng chứng thuật toán luôn tốt hơn. Artifacts cũ: `data/output/network_benchmarks/20261015T174711084670Z/` nếu còn trên máy.

## Kiểm tra

Các bộ kiểm tra liên quan tới cập nhật topology/model:

```powershell
python -m unittest discover -s tests -p test_database_migrations.py -v
python -m unittest discover -s tests -p test_topology.py -v
python -m unittest discover -s tests -p test_routing.py -v
python -m unittest discover -s tests -p test_reset_training.py -v
python -m backend.database.global_coverage --check
```

Lượt cập nhật liên kết đạt 8 kiểm thử migration, 4 kiểm thử topology và 31 kiểm thử routing. Các bài integration dùng SQLite tách biệt, PyTorch thật và kiểm tra không rò nhãn tương lai, checkpoint inference, idempotence, rollback, cách ly scenario, node OFFLINE, tầm nhìn, băng thông và bảo toàn dữ liệu. Kiểm tra cú pháp JavaScript bằng `node --check`; kiểm tra whitespace bằng `git diff --check`. Không chạy seeder demo có thao tác xóa dữ liệu trên database cần giữ: `seed_fl` vẫn là công cụ demo cũ; `seed_db` đã chuyển sang migration bổ sung an toàn.

## Sao lưu và MySQL/XAMPP

XAMPP tiếp tục dùng ở `C:\xampp`, MySQL port 3306; không cần đổi cấu hình XAMPP để chạy migration. Database dự án lấy từ `DATABASE_URL`. Backup SQL trước các cập nhật nằm trong `data/output/database_backups/` và bị bỏ qua bởi Git. Backup phải được giữ ngoài các thay đổi tài liệu Markdown.

Các bản phục hồi MySQL từ phiên xử lý trước được giữ ở `C:\xampp\mysql\recovery-backup-20261022` và `C:\xampp\mysql\data.before-recovery-20261022`; dữ liệu đang chạy ở `C:\xampp\mysql\data`. Không dùng folder backup làm datadir đang hoạt động. Nếu gặp lỗi Start, kiểm tra log lỗi và port trước khi sửa; giữ nguyên dữ liệu gốc và backup SQL.

## Phạm vi và hướng hoàn thiện

### Phản hồi khi thả điểm và giữ menu (25/10/2026)

Mạng 178 node trên toàn cầu không tương đương vùng phủ di động liên tục. Điểm tùy ý thường không có GROUND/AIR/SEA trong tầm điện thoại 2–5 km hoặc thiết bị cứu hộ 10 km; giới hạn vùng cục bộ 300 km không nới rộng khả năng radio. Backend nay trả `coverage_diagnostics.nearest_compatible_nodes` kể cả khi thất bại ngay ở bước lọc vùng, gồm khoảng cách, tầm giả định và trạng thái trong/ngoài vùng. Bảng kết quả hiển thị lý do và các node gần nhất thay vì chỉ “Chưa có tuyến”. Không tự di chuyển điểm hoặc dựng liên kết vượt tầm.

Thiết lập có nút “Thử sự kiện gần trạm trong vùng đã học”: chọn GROUND ACTIVE thuộc pool của checkpoint đang chọn nếu có, đặt một sự kiện mới lệch 0,005 độ vĩ độ (khoảng 0,56 km). Loại sự kiện lấy từ lựa chọn hiện tại, mặc định Message nếu để trống. Không sửa điểm người dùng đã đặt. Với đầu cuối vệ tinh nút yêu cầu chọn thiết bị mặt đất hoặc tự thử cấu hình vệ tinh phù hợp. Chỉ thao tác chủ động mới tạo điểm thử; thao tác này không phải tự tạo hạ tầng phủ sóng toàn cầu.

`frontend/js/shell-navigation.js` điều hướng link nội bộ cùng origin trong khung `page-frame`, giữ sidebar và nguyên pathname/query/hash. Áp dụng cho link FL trực tiếp, link trong các trang con, link trở về địa cầu có target `_top`, và thông điệp điều hướng từ frame hợp lệ. Không bắt link ngoài origin, link tải file, `_blank` hoặc thao tác mở tab bằng phím bổ trợ. Link FL trực tiếp giữ `experiment_id=5` và mở đúng tiến trình thay vì rời shell.

Đã kiểm tra trực tiếp bằng trình duyệt trên port 8000: nút thử tạo Điểm 2 (Message) tại (35,705; 51,42), tới GND-IRN-001 khoảng 0,56 km, dùng checkpoint #5 vòng 10; thả điểm bằng chuột tạo Điểm 3 ngoài vùng phủ và hiển thị các node gần nhất cùng lý do; link FL trực tiếp, liên kết giữa các trang con và quay lại Simulation đều giữ menu. Giữ nguyên Điểm 1 của người dùng. Ảnh kiểm chứng tại `data/output/exports/ui-fixes/local-event.png`, `menu-preserved.png`, `no-coverage-feedback.png`. Không có lỗi JS trong các thao tác đã kiểm tra. Kiểm thử thiết bị bổ sung xác minh chẩn đoán phủ sóng còn tồn tại khi không có node cục bộ.

### Thiết bị sự kiện và kiểm tra vai trò model (25/10/2026)

`source_device=auto` mặc định: Message/Video Call/Watch Video/Gaming dùng `smartphone`; Emergency dùng `emergency_radio`. Có thể chủ động chọn `iot_sensor` hoặc `satellite_terminal`. Các giả định được version hóa trong `backend/services/event_device_service.py` và lưu cùng kết quả `event_model`, gồm thiết bị đã giải quyết, kiểu luồng, chiều truyền, giới hạn băng thông, tầm truy cập và các hạn chế. Điện thoại truy cập GROUND/AIR tối đa 5 km, SEA 2 km; thiết bị cứu hộ 10 km; IoT 2 km. Đầu cuối vệ tinh chỉ truy cập SPACE, giới hạn 5.000 km và góc nâng tối thiểu 10°. Đây là tham số demo có thể sửa tập trung, không phải đặc tả RF hay khoảng cách bảo đảm của 4G/5G. Thiết bị không tự được nâng cấp khi mất kết nối. Chế độ cục bộ 300 km vẫn áp dụng riêng, nên không chứa vệ tinh cao hơn 300 km.

Lọc khả thi trước, suy luận checkpoint sau: lớp truy cập phải được thiết bị hỗ trợ, trong tầm và tầm nhìn; tốc độ thiết bị phải đáp ứng nhu cầu. Băng thông tiếp cận bị giới hạn bởi cả node và thiết bị. Video tải xuống dùng tốc độ downlink; gọi/game lấy giới hạn hai chiều. Link hiện đối xứng, chưa mô phỏng bất đối xứng đường lên/xuống. Đích `destination` ghi rõ dịch vụ biên tại GROUND đã chọn. Các GROUND được giả định có đủ dịch vụ biên; GROUND/AIR/SEA tương thích được giả định mang trạm truy cập, chưa có inventory radio/app từng node. Ước tính ứng dụng cộng thêm xử lý thiết bị/máy chủ. Kiểu luồng continuous/burst là metadata mô tả dịch vụ; chưa sinh hàng đợi hay từng gói theo thời gian. Băng thông vẫn giữ tới khi xóa/tính lại sự kiện, chưa có hết hạn phiên tự động.

`legacy_simulator` chỉ phục vụ tái lập phép thử trước khi có thiết bị; không xuất hiện trong danh sách lựa chọn giao diện và không phải chế độ mô phỏng thiết bị thực tế. Các kiểm thử đồ thị/cấp phát cũ chọn rõ legacy để giữ nguyên mục tiêu; 5 kiểm thử mới xác minh auto-device, cấm điện thoại nối trực tiếp vệ tinh, capacity/elevation, lưu profile, gọi checkpoint thật và kiểm tra thay đầu ra dự đoán thực sự thay tuyến được chọn.

Kết quả predictive lưu `routing_decision`: experiment, round, số kênh suy luận, phương pháp chọn và điều kiện khả thi. `model_applicability` ghi target, payload huấn luyện/ứng dụng, các node tuyến ngoài pool đã học và MAE holdout. Model hiện học RTT tick kế tiếp cho payload FL 3.844 byte, chưa học trực tiếp độ trễ end-to-end ứng dụng hay chính sách routing. Dữ liệu huấn luyện là kênh đại diện mỗi client, trong khi định tuyến áp dụng model cho từng link/thiết bị: đây là chuyển miền cần đối chứng, không tự được xem là đã xác thực. Experiment #5: MAE 4,70044 ms so với persistence 4,70241 ms, chênh khoảng 0,00197 ms trên holdout FL; chưa chứng minh cải thiện định tuyến.

File `data/output/exports/local_route_check/device-checks.json` chứa 5 dịch vụ tại (24,66; 46,71), tự chọn thiết bị, dùng checkpoint #5 round 10, đường đến GND-SAU-001 khoảng 1,50257 km. Mỗi trường hợp chỉ có một kênh truy cập hợp lệ nên không dùng demo này để kết luận FL chọn tuyến tốt hơn baseline. Điểm cũ (24,8; 46,85), cách trạm 22,53 km, nay trả `no_coverage` với điện thoại: chỉ nằm trong vùng cục bộ chưa đủ điều kiện radio. Snapshot cũ không tự sửa. Khi kiểm tra, danh sách điểm production đã được xóa từ phía ứng dụng; không khôi phục hoặc tạo thêm điểm thay người dùng.

Đã đạt 37 kiểm thử routing, 15 lưu sự kiện và 5 thiết bị sự kiện sau cập nhật, cùng kiểm tra cú pháp JS. Giao diện có lựa chọn auto-device và hiển thị thiết bị, hướng/kiểu lưu lượng, đích và checkpoint đã sử dụng; chưa xác minh trực quan lại trong browser do chặn truy cập tab ở phiên trước.

### DQN, DRQN và QR-DQN: hướng nghiên cứu, chưa triển khai

FL là cách phối hợp huấn luyện; DQN/DRQN/QR-DQN là các phương pháp học quyết định, không thay thế khái niệm FL. DQN xấp xỉ Q(s,a), học hành động tối đa hóa phần thưởng tích lũy: [bài gốc DQN](https://deepmind-media.storage.googleapis.com/dqn/DQNNaturePaper.pdf). DRQN thêm trạng thái hồi tiếp LSTM để tích hợp lịch sử khi quan sát không đầy đủ: [bài gốc DRQN](https://arxiv.org/abs/1507.06527). QR-DQN học các quantile của phân phối return thay vì chỉ kỳ vọng: [bài gốc QR-DQN](https://arxiv.org/abs/1710.10044). QR-DQN không tự đảm bảo giảm p95 latency hoặc rủi ro; cần reward và tiêu chí chọn hành động tương ứng. Tên “DQRN” cần đối chiếu tài liệu người dùng để xác định đang muốn nói DRQN hay QR-DQN.

Một thiết kế routing RL có thể dùng trạng thái: vị trí/node hiện tại, đích, nhu cầu dịch vụ, tải, hàng đợi, dung lượng còn lại, năng lượng và thời gian liên kết còn tồn tại; hành động là chọn next-hop trong các hàng xóm hợp lệ hoặc chờ khi dịch vụ cho phép; reward gồm thưởng giao thành công và phạt độ trễ chuẩn hóa, năng lượng, chuyển tuyến, mất gói. Phải mask liên kết không tương thích/mất vùng phủ/thiếu tài nguyên, chặn vòng lặp và timeout. Dữ liệu cần trajectory (s,a,r,s_next,done,valid-action-mask), không thể lấy nguyên observations dự đoán RTT hiện tại để huấn luyện DQN. Môi trường phải cập nhật theo thời gian và hành động phải ảnh hưởng trạng thái. Kiểm thử trên seed/tải/quỹ đạo chưa thấy, so sánh cùng điều kiện với shortest-path tĩnh, FL + shortest-path, rồi DQN; đánh giá delivery ratio, p50/p95 delay, vi phạm QoS, năng lượng và handover.

Hướng trước mắt là chuẩn hóa telemetry/link label theo ứng dụng và kiểm chứng FL-routing trước khi tăng độ phức tạp. DRQN đáng thử khi thiếu quan sát và có lịch sử; QR-DQN khi cần mô tả phân phối kết quả. Có thể nghiên cứu huấn luyện phân tán các agent qua FL nhưng đồng bộ tham số/replay, chính sách khác nhau và dữ liệu non-IID cần thiết kế riêng; FedAvg hiện tại không tự biến thành federated RL. Chưa thay hoặc huấn luyện lại mô hình thành RL trong lượt cập nhật này.

### Định tuyến cục bộ và demo thật (25/10/2026)

Yêu cầu định tuyến mới mặc định `routing_scope=local`, `local_radius_km=300`. Chỉ xét node ACTIVE cách sự kiện không quá giới hạn này theo khoảng cách không gian 3D (tính cả độ cao), GROUND đích cũng phải ở trong vùng; mỗi hop không vượt cùng giới hạn. Link đã lưu được kiểm tra lại tầm nhìn và tính lại khoảng cách từ tọa độ hiện tại, không dùng số km cũ để vượt giới hạn. Tiếp cận vẫn chịu giới hạn lớp GROUND 50, SEA 200, AIR 1.500, SPACE 5.000 km và tầm nhìn hình học. Đây là giả định demo, chưa có link budget, đo RF hay mô hình tranh chấp gói tin thực tế.

Không có tuyến cục bộ thì trả lỗi rõ ràng, không tự mở vùng hoặc điều động tài nguyên từ xa. Trên giao diện phải chủ động bật “Cho phép tuyến toàn scenario và điều động từ xa” để dùng lại chế độ `global`. `access_radius_km` chỉ là giới hạn bổ sung ở đầu vào; khác với `local_radius_km` vốn giới hạn cả node trung chuyển, đích và mỗi hop. Tổng quãng đường nhiều hop có thể lớn hơn bán kính; các hop và mọi node vẫn phải thỏa giới hạn. Các snapshot sự kiện cũ giữ kết quả đã lưu cho tới khi người dùng yêu cầu tính lại. Đường cục bộ trên địa cầu vẽ theo tọa độ snapshot lúc tính để số km không bị sai lệch theo quỹ đạo đang hoạt họa.

Đã huấn luyện thật experiment #5 trên MySQL: Predictive, 9 client cùng vùng, 10 vòng, 2.000 lịch sử và 10 online/client, model 961 tham số. Trong phép kiểm tra trước sửa, sự kiện tại (28, 50) qua SAT-POLAR-026 → GND-SAU-001 với tổng khoảng 3.113,82 km. Cùng điểm đó sau giới hạn cục bộ 300 km trả `no_local_nodes`, không dựng tuyến thay thế từ xa. Điểm ở vị trí từng dùng trong ảnh (40,6954; 171,432) cũng không có tuyến cục bộ.

Đã lưu đúng một sự kiện demo mới, ID 17, tọa độ (24,8; 46,85), dùng checkpoint #5: trực tiếp tới GND-SAU-001, quãng đường 22,53275 km, không điều động, ước tính một chiều 16,28668 ms. Có một chặng tiếp cận và 0 hop backbone vì đã tới trạm đích. File chứng cứ tại `data/output/exports/local_route_check/`: `training.json`, `before.json`, `after.json`, `saved-event.json`; chứa cấu hình, kết quả từng vòng và tuyến trước/sau. Những số này là kết quả mô phỏng trên dữ liệu thật của ứng dụng, không phải độ trễ đã đo ngoài đời.

### Client theo khu vực (25/10/2026)

FL Training mặc định dùng `pool_mode=regional`, bán kính 1.500 km. Có thể nhập cả vĩ độ và kinh độ tâm; nếu để trống cả hai, hệ thống chọn vùng đông client nhất trong các tâm GROUND đủ điều kiện, hoặc dùng các node khác làm tâm khi không có GROUND. Khi bằng nhau, chọn theo ID để tái lập. Chỉ xét node ACTIVE trong participant pool hiện tại (nếu đã chọn participant); không đủ client thì báo lỗi, không tự tăng bán kính. `pool_mode=all` chủ động dùng toàn bộ pool của scenario. Các experiment cũ thiếu trường này được giao diện khôi phục dưới phạm vi toàn scenario.

Form, `/api/fl/training-context`, `/api/fl/preview` và thao tác tạo experiment dùng cùng cách lọc. Nút dùng tất cả chỉ lấy client trong phạm vi đang chọn. Dataset mạng mới ở chế độ regional chỉ sinh dữ liệu cho nhóm đó; dataset cũ có thể được tái sử dụng nếu chứa đầy đủ client của nhóm. Cấu hình experiment lưu `candidate_pool` và `training_region` để kiểm tra tâm, bán kính, khoảng cách từng client và vị trí chọn vùng. GROUND cũng có thể là client; một node có thể tham gia nhiều experiment. Backend thực hiện FedAvg, chưa gán một ground cụ thể làm aggregator hay triển khai FL phân cấp.

Khoảng cách khu vực là cung tròn lớn của vị trí chiếu xuống mặt đất tại snapshot trong database. Mỗi client cách tâm không quá R; hai client có thể cách nhau gần 2R. Việc thuộc cùng nhóm không xác nhận tầm nhìn, liên kết vô tuyến hoặc tuyến truyền đến aggregator. Chọn tất cả client không tạo liên kết tất cả với nhau. Các cung FL trên địa cầu chỉ minh họa trao đổi với bộ tổng hợp logic. Không coi nhóm địa lý là lời giải cho tuyến ứng dụng quá xa hoặc cho chuyển động quỹ đạo theo thời gian.

Tự huấn luyện khi tìm tuyến mới dùng tâm sự kiện, bán kính 1.500 km và tối đa 5 client/vòng trong nhóm đủ điều kiện (cần ít nhất 2). Đối chứng RTT tập trung học dữ liệu trong pool đã chọn. Đối chứng MNIST tập trung vẫn học toàn bộ tập train chuẩn, không chia theo node; giao diện và preview nêu rõ ngoại lệ này. Chương trình `backend.network_volume_demo` giữ `pool_mode=all` để tái lập thí nghiệm toàn scenario trước đó.

Demo SQLite riêng tại `data/output/training_ui_check/regional-smoke.json` lưu request, nhóm client, dự toán, ví dụ quan sát đầu vào và kết quả từng vòng. Snapshot demo 178 node chọn được 9 client quanh GND-SAU-001, bán kính 1.500 km: 4 GROUND, 2 SPACE, 1 AIR, 2 SEA. Với 2.000 lịch sử và 2 online/client: 10.800 train, 3.600 validation, 3.600 test, 18 online; tổng 18.018 mẫu. Hai vòng Predictive hoàn tất, MAE lần lượt khoảng 5,079854 và 5,079389 ms; đây là kiểm tra luồng, không phải bằng chứng cải thiện chất lượng so với mức dữ liệu khác.

Tiện ích `python -m backend.delete_experiment --id <ID> --expect-latest` chỉ xem trước. Thêm `--apply` để lưu và kiểm tra backup gzip trước khi xóa đúng experiment terminal cùng các round liên quan; từ chối job đang chạy và giữ dataset, observations, node/link, participant, snapshot tuyến. Experiment production #4 đã xóa ở phiên trước; backup nằm tại `data/output/training_reset_backups/20261024T200611711021Z-experiment-4/`. Không chạy lại thao tác xóa. Phiên tiếp tục chưa đọc lại được MySQL vì dịch vụ và ứng dụng cổng 8000 đang tắt.

Kiểm thử sau thay đổi: 15 bài network learning, 33 bài routing, 7 bài MNIST runtime và 2 bài xóa experiment đều đạt trên DB tạm. Kiểm tra cú pháp JavaScript và whitespace được thực hiện riêng. Kiểm tra giao diện trực tiếp của phiên này chưa hoàn tất vì trình duyệt chặn quyền truy cập tab demo; các con số demo được xác minh qua API.

### Demo lượng dữ liệu và chế độ mạng (25/10/2026)

`python -m backend.network_volume_demo --seeds 11 42 71 --rounds 10 --clients 24` tạo database SQLite mới, chạy Predictive với cùng model 961 tham số trên 178 client. Sinh 2.000 mẫu lịch sử/client; so sánh 1.200 train với tập con 192 train gần nhất, giữ chung 400 validation, 100 online và 400 test/client. Mức nhỏ là thiết kế fixed-holdout với 992 lịch sử thực tế, không phải dataset 320 lịch sử chia độc lập. Giữ epochs nên ngân sách tính toán lớn hơn ở mức nhiều dữ liệu. Không sửa MySQL, checkpoint cũ hoặc giới hạn nhập số.

Đã bổ sung `bursty_congestion` (nghẽn 8/47 tick) và `regime_switching` (trạng thái 60 tick) cho telemetry FL, API, CLI và lựa chọn profile trên FL Training. Các profile cũ giữ generator v1; profile mới ghi `sagsin-network-v2-dynamic` và thông số mô phỏng trong metadata. Không đưa lịch tương lai vào feature; routing chưa mô phỏng các trạng thái thời gian này. Bộ sinh observation ghi theo lô 2.000 mẫu để không giữ toàn bộ ORM objects trong RAM khi sinh dataset lớn.

Artifacts trong `data/output/network_benchmarks/volume_<timestamp>/`: SQLite, source CSV, metadata, requests, per-round audit/outcomes, checkpoints và bảng so sánh nhiều seed. Chạy `python -m backend.network_volume_report data/output/network_benchmarks/volume_<timestamp>` để kiểm chứng cùng holdout, suy luận lại từ checkpoint và tạo `report.html`. Tài liệu bảo vệ theo yêu cầu nằm ở `document/10_cau_hoi_bao_ve_FL_SAGSINs.md`.

- Đã có FL regression, participant scheduling, inference checkpoint, định tuyến nhiều hop theo snapshot và so sánh với công thức trên cùng điều kiện. Chưa chứng minh tối ưu toàn cục hoặc hiệu quả độ trễ ứng dụng ngoài đời.
- FL hiện dự đoán RTT payload model tick tiếp theo; cần dataset theo link/t+1, hàng đợi, payload ứng dụng và đo end-to-end để kiểm chứng xếp hạng tuyến ứng dụng. Không coi R² cao hay một seed tốt là đủ bằng chứng.
- Cần đồng hồ mô phỏng chung, lan truyền quỹ đạo, contact duration/handover và ràng buộc năng lượng/hải trình UAV/tàu. Đã giữ băng thông theo nhu cầu của nhiều sự kiện đồng thời; chưa mô phỏng hàng đợi, chia thời gian hoặc tranh chấp từng gói tin.
- Client hiện là phân vùng logic trong DB chung, chưa là tiến trình/thiết bị độc lập qua socket. Chưa triển khai Differential Privacy, NbFML hoặc QR-DQN/DRL. Các run đang dở chưa tự resume sau restart.
- Tài liệu dự án được hợp nhất ở README.md này; ghi hướng dẫn, giả định, kết quả kiểm tra và giới hạn mới tại đây thay vì tạo thêm file Markdown.
