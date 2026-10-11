# Đề xuất phân tách chức năng Network, Participants và FL

Tài liệu này mô tả vai trò của từng mục, luồng dữ liệu/API tương ứng và trạng
thái triển khai. Các trang Network, Participants, Experiments và Results đã
được dựng trong workspace theo phân tách dưới đây; cần chạy ứng dụng để kiểm
tra trực tiếp với database đang cấu hình.

## Ưu tiên trước khi triển khai giao diện

Các trang Network, Participants, Experiments và Results phụ thuộc vào ý nghĩa
ổn định của participant, trạng thái client và metric. Vì vậy, lộ trình FL dưới
đây được ưu tiên trước toàn bộ các giai đoạn giao diện ở mục 5. Không bắt đầu
chia trang UI cho đến khi baseline và cách ghi kết quả đã đủ tin cậy.

### P0 — Ổn định baseline FedAvg

- Giữ một bộ cấu hình baseline có thể tái lập: scenario, tập dữ liệu và cách
  chia shard, model, optimizer, seed, số round, số client, network profile,
  timeout và dropout. Lưu đầy đủ cấu hình thực chạy cùng experiment.
- Chạy bộ test sẵn có trước và sau mỗi thay đổi thuật toán. Các file test rỗng
  không được tính là coverage.
- Đã sửa lỗi thời lượng round bỏ qua client TIMEOUT: client timeout hiện được
  tính đến deadline cấu hình trong communication time và round duration; năng
  lượng ước tính lấy theo round duration đã hiệu chỉnh. Dropout mô phỏng xảy ra
  trước truyền dữ liệu nên có communication time bằng 0. Đây là quy ước mô
  phỏng cần giữ nhất quán và giải thích trong kết quả.
- Baseline cần được xem là ổn định khi cùng cấu hình/seed cho cùng tập client,
  partition và kết quả tái lập trong giới hạn sai số số học; mọi thay đổi ngẫu
  nhiên phải dùng RNG được seed rõ ràng.

### P1 — Hoàn thiện Delay-Aware FL (bước thuật toán tiếp theo)

Đây là chức năng thuật toán tiếp theo sau baseline. `backend/algorithms/delay_aware_fl.py`
hiện có worker huấn luyện dạng FedAvg; `backend/services/scheduling_service.py`
và `backend/services/delay_service.py` là các điểm cần kiểm tra/tách trách
nhiệm khi triển khai scheduler, chưa được xem là thuật toán delay-aware hoàn
chỉnh chỉ dựa trên tên module.

- Xây tiêu chí chọn/sắp lịch từ latency, bandwidth và trạng thái node (ACTIVE,
  offline/busy, năng lượng hoặc giới hạn tài nguyên nếu dữ liệu có sẵn).
- Tách candidate pool khỏi quyết định scheduler: cùng scenario và tập ứng viên
  phải được dùng trong lần chạy so sánh; scheduler mới quyết định thứ tự/chọn
  client đủ điều kiện.
- Định nghĩa rõ timeout và dropout: client offline/không đủ điều kiện bị loại
  trước khi chạy; dropout sau khi được chọn; timeout chờ đến deadline; chỉ client
  hoàn thành local training mới được aggregation. Nếu không còn client hoàn
  tất, round phải ghi trạng thái/thất bại có lý do thay vì để metric mơ hồ.
- Mỗi round lưu accuracy/loss trên cùng test set, thời gian hoàn tất round,
  communication time, năng lượng ước tính, số client được chọn/hoàn tất/
  timeout/dropout, cùng outcome từng client. Phân biệt metric đo thật với metric
  ước tính/mô phỏng.
- Cấu hình scheduler và các tham số của nó phải nằm trong experiment snapshot
  để có thể tái lập và hiển thị lại.

### P2 — So sánh FedAvg và Delay-Aware FL

Chạy hai thuật toán trên cùng scenario, candidate pool, seed, số round, model,
dataset/partition, optimizer, local epochs, batch size, network profile,
timeout và dropout. Chỉ thay chính sách chọn/sắp lịch client. So sánh accuracy
theo round, thời gian truyền và hoàn tất round, năng lượng ước tính, số client
được chọn/hoàn tất và tỷ lệ timeout/dropout. Lưu cấu hình ghép cặp để có thể
đối chiếu đúng hai experiment; không so sánh các run khác scenario hoặc khác
partition như thể chỉ khác thuật toán.

### P3–P4 — Mở rộng sau khi có kết quả đối chứng

1. Thêm Differential Privacy sau khi baseline và delay-aware metrics đã ổn
   định; ghi rõ epsilon/delta, cơ chế clipping/noise và ảnh hưởng lên accuracy.
2. Sau đó nghiên cứu QR-DQN cho participant selection, có state/action/reward
   và baseline so sánh được định nghĩa rõ. Đây là nhánh mở rộng lớn, không gộp
   vào P1.

### P5 — Phân tách giao diện

P0 đã được ổn định. Theo chỉ đạo mới nhất, các trang chức năng được triển khai
ngay sau P0 dựa trên API/metric hiện có; không chờ hoàn tất P1–P2. Sau khi các
trang này được xác nhận trực tiếp, tiếp tục P1 Delay-Aware FL rồi P2 so sánh
đối chứng. Những metric chưa có trong API cần hiển thị là chưa có, không giả lập
thêm ở giao diện.

## 1. Hiện trạng trong project

| Mục sidebar | Hành vi hiện tại | Backend/UI hiện có |
| --- | --- | --- |
| Simulation | Hiện quả địa cầu 3D và marker từ database | `app.js` gọi `/api/nodes`; node có bốn loại SPACE/AIR/GROUND/SEA |
| Dashboard | Mở `/dashboard.html` | Có KPI topology, layer, participant, biểu đồ round và experiment gần đây |
| Network | Bảng node có tìm kiếm/lọc và bảng links đã lưu | `/api/nodes`, `/api/links`; links chỉ phản ánh dữ liệu database, không tự suy diễn topology |
| Participants | Bảng pool, thêm node hiện có, cập nhật selected/local epochs | `/api/participants/` GET/POST và `PATCH /{id}`; API ngăn chọn node không ACTIVE và participant trùng node |
| FL Training | Mở `/fl.html` | Có form cấu hình/chạy MNIST FedAvg và theo dõi experiment vừa tạo |
| Experiments | Lịch sử run, lọc theo thuật toán/trạng thái và mở Results | `/api/fl/experiments` list/detail |
| Results | Chọn experiment, biểu đồ metric theo round, bảng round và client | Detail API trả metric aggregate từng round; dashboard vẫn overview experiment mới nhất |

Trước thay đổi, `frontend/js/app.js` gán `FL Training`, `Experiments` và
`Results` cùng tới `/fl.html`; Network và Participants chưa có chức năng. Route
map hiện mở từng trang riêng, và giao diện dùng API database thay vì dữ liệu
placeholder.

## 2. Nguyên tắc phân tách

- **Network trả lời:** topology hiện gồm node/link nào, vị trí và trạng thái ra sao?
- **Participants trả lời:** node nào được đăng ký làm client FL, được chọn hay
  chưa, và cấu hình local training của client là gì?
- **FL Training trả lời:** cấu hình và khởi chạy một lần huấn luyện mới như thế nào?
- **Experiments trả lời:** những lần chạy nào đã có, trạng thái/cấu hình của từng lần?
- **Results trả lời:** một lần chạy đạt kết quả gì theo round và theo client?
- **Dashboard trả lời:** tình hình tổng quan nhanh của toàn project/scenario.

Dashboard có thể liên kết sang các trang chuyên sâu, nhưng không nên thay thế
Network, Participants, Experiments hay Results.

## 3. Vai trò và nội dung của từng trang

### Network

**Mục tiêu:** xem và quản lý topology SAGSIN.

**Nội dung đề xuất:**

1. Thẻ tổng quan: tổng node, số node theo SPACE/AIR/GROUND/SEA, số link active,
   số node offline.
2. Bảng node có tìm kiếm và lọc theo layer, platform, quốc gia, trạng thái và
   simulated/real-data flag.
3. Chi tiết node: ID, layer/platform, vị trí WGS84, altitude, country/location,
   bandwidth, latency, battery, status và metadata quỹ đạo nếu là vệ tinh.
4. Tab Network Links: source/target, khoảng cách, bandwidth, latency và status.
5. Trạng thái rỗng rõ ràng khi chưa có link; không tự tạo hoặc tuyên bố link
   thực tế chỉ vì có node trên globe.

**API đang có:** `GET /api/nodes`, `POST /api/nodes` và `GET /api/links`.

**API chưa có:** cập nhật trạng thái/tạo/xóa node hoặc link. Trước khi thêm cần kiểm tra node
trùng ID, loại node hợp lệ, latitude trong [-90, 90], longitude trong [-180,
180], và source/target của link phải tồn tại.

**Ranh giới:** trang này quản lý hạ tầng/mạng; không chọn client cho một
experiment cụ thể và không hiển thị metric accuracy/loss theo round.

### Participants

**Mục tiêu:** chuẩn bị danh sách client và cấu hình local-training để FL có thể
chọn.

**Nội dung đề xuất:**

1. Bảng participant nối với node tương ứng: node ID, layer/platform, quốc gia,
   node status, selected, local epochs và số sample gần nhất.
2. Lọc theo layer/status/quốc gia; bật/tắt `selected` hàng loạt hoặc từng client.
3. Tạo participant cho một node đã tồn tại; kiểm tra mỗi node chỉ có một
   participant record.
4. Chỉ cho chọn node ACTIVE (hoặc hiển thị lý do node không đủ điều kiện).
5. Thông báo số client đang được chọn để đối chiếu với `client_count` trên form
   FL Training.

**API đang có:** `GET /api/participants/`, `POST /api/participants/` và
`PATCH /api/participants/{id}` cho selected/local epochs.

**API còn thiếu:** DELETE participant nếu có yêu cầu gỡ record. API hiện xác nhận
node tồn tại và tránh tạo participant trùng `node_id` ở tầng route.

**Lưu ý quan trọng về dữ liệu:** hiện `dataset_size` không đại diện cho bộ dữ
liệu riêng được upload/lưu tại node. FL service tự phân hoạch MNIST trên server
thành IID hoặc Non-IID, rồi cập nhật `dataset_size` theo số sample của shard
được gán sau khi bắt đầu training. Vì vậy UI nên gọi đây là “sample được gán ở
lần chạy gần nhất”, không mô tả như dung lượng dataset thực của thiết bị.

**Luồng với FL Training:** nếu có participant selected, backend chọn từ nhóm
đó; nếu không có selected participant, backend lấy ngẫu nhiên các node active
đủ số lượng và tạo/cập nhật participant records tương ứng.

### FL Training

**Mục tiêu:** cấu hình và khởi chạy một experiment mới.

Giữ form hiện tại tại `/fl.html`: scenario, thuật toán, rounds, client count,
local epochs, learning rate, batch size, IID/Non-IID, network profile, dropout,
timeout và seed. Khi submit, gọi `POST /api/fl/experiments`; backend tạo record
QUEUED và chạy background. Trang có thể tiếp tục hiển thị tiến trình của
experiment vừa tạo, nhưng không nên trở thành nơi duyệt toàn bộ lịch sử.

**Kết quả thao tác:** hiện thông báo thành công/lỗi và liên kết “Mở experiment”
sang trang Experiments hoặc Results kèm experiment ID.

### Experiments

**Mục tiêu:** lịch sử và trạng thái các lần chạy.

**Trang đề xuất:** `experiments.html` và `experiments.js`, đọc
`GET /api/fl/experiments`. Bảng gồm ID, scenario, algorithm, ngày tạo, trạng
thái, số round hoàn tất/tổng round và accuracy/loss gần nhất. Có filter theo
scenario, algorithm, status; mỗi hàng mở chi tiết theo experiment ID qua
`GET /api/fl/experiments/{id}`.

Trang không có form khởi chạy riêng để tránh trùng FL Training. Có thể có nút
“Run again” điều hướng về FL Training và điền lại cấu hình cũ ở giai đoạn sau.

### Results

**Mục tiêu:** phân tích kết quả của một experiment cụ thể hoặc so sánh một số
experiment.

**Trang đề xuất:** dùng `results.html` và `results.js`. Chọn experiment hoặc
nhận `experiment_id` từ URL; hiển thị accuracy/loss theo round, latency,
communication time, bandwidth, energy, packet loss, thời gian train và trạng
thái từng client. Cần có empty/loading/error state và ghi rõ metric nào là đo
trên MNIST test set, metric nào là mô phỏng mạng.

**API hiện có:** `GET /api/fl/experiments/{id}` trả cấu hình, round, kết quả
client và aggregate metrics theo round (`latency_ms`, `communication_time_ms`,
`energy_j`, `bandwidth_mbps`, `data_transferred_mb`, `packet_loss_ratio`).
Dashboard vẫn dùng `/api/dashboard/stats` cho dữ liệu overview.

### Dashboard

Giữ trang hiện tại làm overview: KPI topology, layer counts, participant counts,
experiment mới nhất, biểu đồ tổng hợp và cảnh báo. Thêm link “Xem Network”,
“Quản lý Participants”, “Xem Experiments”, “Xem Results” để mở trang chuyên sâu.

## 4. Bản đồ điều hướng đích

| Sidebar | Trang | Trách nhiệm |
| --- | --- | --- |
| Simulation | Globe hiện tại | Quan sát vị trí node và chọn vị trí event |
| Dashboard | `/dashboard.html` | Tổng quan nhanh |
| Network | `/network.html` | Node/link inventory và topology |
| Participants | `/participants.html` | Cấu hình FL client pool |
| FL Training | `/fl.html` | Tạo/chạy experiment mới |
| Experiments | `/experiments.html` | Lịch sử, trạng thái và cấu hình từng lần chạy |
| Results | `/results.html` | Metric và phân tích kết quả |

Mỗi menu có một route riêng. Sidebar nên gom logic chuyển trang vào một mapping
duy nhất; các mục chưa triển khai phải hiện empty/coming-soon state rõ ràng,
không trỏ tạm sang một trang khác có chức năng khác.

## 5. Trạng thái triển khai và việc còn lại

Các giai đoạn dưới đây đã được triển khai ở mức giao diện/API trong workspace.
Phần cần xác nhận tiếp là luồng chạy trực tiếp với database và polish theo phản
hồi sử dụng.

### Đã triển khai — Điều hướng và trang Network read-only

1. Sửa route map cho Network và Participants; tạo `experiments.html`; trỏ
   Experiments sang trang mới; trỏ Results sang `results.html`.
2. Xây Network page với `GET /api/nodes`, bộ lọc/bảng/chi tiết node.
3. Bổ sung `GET /api/links`; hiển thị empty state cho scenario chưa có link.
4. Kiểm tra route nào cũng mở đúng page riêng, active sidebar đúng mục, iframe
   không bị giữ URL trang cũ khi chuyển về Simulation.

### Đã triển khai — Participant management

1. Dựng trang từ `GET /api/participants/` và node list.
2. Thêm `PATCH` để chỉnh selection/local epochs; thêm create flow nếu node chưa
   có participant.
3. Enforce một participant trên mỗi node và validate ACTIVE/client count.
4. Đồng bộ selected count sang form FL Training; mô tả đúng ý nghĩa dataset_size.

### Đã triển khai — Tách FL Training khỏi Experiment history

1. Giữ `/fl.html` tập trung vào tạo run và trạng thái run vừa gửi.
2. Dựng `experiments.html` từ API list/detail; filter, progress, trạng thái,
   cấu hình và liên kết sang kết quả.
3. Xử lý trạng thái QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED và empty state.

### Đã triển khai — Results theo experiment

1. Bổ sung aggregate metrics vào API detail theo từng round.
2. Dựng `results.html` với experiment selector, chart accuracy/loss/network/
   energy và bảng client outcomes.
3. Phân biệt rõ MNIST test metrics với network metrics mô phỏng; không gộp
   kết quả của các experiment khác nhau nếu chưa chọn chúng.

### Đã triển khai — Hoàn thiện trải nghiệm

1. Thêm loading/error/empty state thống nhất, responsive layout và links chéo.
2. Kiểm tra luồng menu theo từng trang, refresh, quay lại globe, và deep link
   experiment ID.
3. Đối chiếu số liệu trên trang với API/database; không dùng dữ liệu giả để lấp
   bảng rỗng.

## 6. Tiêu chí hoàn thành

- Network, Participants, FL Training, Experiments và Results mở năm màn hình có
  mục tiêu khác nhau; không còn route trỏ nhầm cùng `/fl.html`.
- Network hiển thị node; link hiển thị dữ liệu thật hoặc empty state nếu chưa có.
- Participants cho biết node nào được chọn và cấu hình client; thay đổi selection
  được backend lưu và FL Training dùng đúng nhóm client đó.
- FL Training chỉ tập trung tạo/chạy run và theo dõi run mới.
- Experiments liệt kê và mở đúng experiment; Results hiển thị metric đúng
  experiment/round/client.
- Dashboard giữ vai trò overview và điều hướng được sang các trang chi tiết.
- UI báo lỗi API rõ ràng, có trạng thái loading/empty, không tự tạo dữ liệu giả.

## 7. Tệp tham chiếu hiện tại

- Điều hướng sidebar: `frontend/js/app.js`
- Sidebar markup: `frontend/html/index.html`
- FL Training form/progress: `frontend/html/fl.html`, `frontend/js/fl.js`
- Dashboard overview: `frontend/html/dashboard.html`, `frontend/js/dashboard.js`
- Node API: `backend/routers/network.py`
- Participant API/schema/model: `backend/routers/participants.py`,
  `backend/schemas/participant.py`, `backend/models/participant.py`
- Experiment APIs: `backend/routers/federated_learning.py`, `backend/schemas/fl.py`
- MNIST client selection/partition/metrics: `backend/services/fl_service.py`
- Link storage model: `backend/models/network.py` (`NetworkLink`)
