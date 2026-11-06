"""Read-only, offline export of one completed distributed experiment for review.

Raw client data is read explicitly by this operator tool, never by the FL server.
No provisioning, data generation, training, or database updates are performed.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False,
                               default=str), encoding="utf-8")


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        raise ValueError(f"No data to export: {path.name}")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    # BOM lets Excel open Vietnamese labels correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
                             else value for key, value in row.items()})
    return len(rows)


def export(experiment_id, destination):
    import torch
    from backend.database.database import engine
    from backend.models.simulation import Experiment
    from backend.models.network_learning import NetworkDataset
    from backend.services.distributed_runtime_service import RUNTIME, directory
    from sagsin.config import ExperimentConfig
    from sagsin.database import credentials
    from sagsin.dataset import reuse_local
    from sagsin.model import predictions, validate_envelope

    with Session(engine) as db:
        experiment = db.get(Experiment, experiment_id)
        if experiment is None or experiment.status != "COMPLETED":
            raise ValueError("Choose a completed experiment")
        config = experiment.config_json
        if config.get("runtime") != RUNTIME:
            raise ValueError("This exporter supports the distributed runtime only")
        dataset = db.get(NetworkDataset, config["dataset_id"])
        dataset_metadata = {column.name: getattr(dataset, column.name)
                            for column in NetworkDataset.__table__.columns}
        experiment_metadata = {column.name: getattr(experiment, column.name)
                               for column in Experiment.__table__.columns}
    source = directory(config)
    result = json.loads((source / "result.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((source / "checkpoint.json").read_text(encoding="utf-8"))
    runtime = ExperimentConfig.from_saved(result["config"])
    source_run = runtime.dataset_run_id or config["runtime_id"]
    if runtime.topology != dataset_metadata["config_json"]["topology"]:
        raise ValueError("Dataset and experiment topology differ")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    file_rows = {}
    fingerprints = {}
    all_rows = []
    accounts = credentials()["clients"]
    clients = list(result["clients"])
    print(f"Exporting experiment {experiment_id}, dataset {dataset.id}, {len(clients)} clients", flush=True)
    for index, client in enumerate(clients):
        # Verifies configuration, immutable rows, and the stored per-client hash.
        parts, fingerprint = reuse_local(accounts[client], source_run, runtime)
        expected = dataset_metadata["config_json"].get("client_fingerprints", {}).get(client)
        if expected and fingerprint != expected:
            raise ValueError(f"Dataset metadata fingerprint differs: {client}")
        fingerprints[client] = fingerprint
        for split, rows in parts.items():
            for row in rows:
                if row["client_id"] != client or row["split"] != split:
                    raise ValueError("Client or split identity mismatch")
                all_rows.append(dict(experiment_id=experiment_id, dataset_id=dataset.id,
                                     source_run_id=source_run, **row))
        if (index + 1) % 40 == 0:
            print(f"Verified {index + 1}/{len(clients)} client datasets", flush=True)

    def csv_out(name, rows):
        file_rows[name] = write_csv(destination / name, rows)

    input_dir = "01_input"
    csv_out(f"{input_dir}/observations.csv", all_rows)
    for split in ("train", "validation", "test"):
        csv_out(f"{input_dir}/{split}.csv", (row for row in all_rows if row["split"] == split))
    topology = runtime.topology
    csv_out(f"{input_dir}/nodes.csv", topology["nodes"])
    csv_out(f"{input_dir}/links.csv", topology["links"])
    write_json(destination / input_dir / "topology.json", topology)
    write_json(destination / input_dir / "dataset_metadata.json", dataset_metadata)
    counts = Counter(row["split"] for row in all_rows)
    csv_out(f"{input_dir}/split_counts.csv", [dict(split=k, rows=v) for k, v in counts.items()])

    training_dir = destination / "02_training"
    write_json(training_dir / "experiment.json", experiment_metadata)
    write_json(training_dir / "config.json", result["config"])
    shutil.copy2(source / "checkpoint.json", training_dir / "checkpoint.json")
    shutil.copy2(source / "result.json", training_dir / "saved_result.json")
    csv_out("02_training/round_metrics.csv", [dict(
        experiment_id=experiment_id, round=r["round"], selected_clients=len(r["selected"]),
        validation_samples=r["validation"]["count"], validation_mae_ms=r["validation"]["mae_ms"],
        validation_rmse_ms=r["validation"]["rmse_ms"], persistence_mae_ms=r["persistence"]["mae_ms"],
        wall_s=r["wall_s"], aggregation_s=r["aggregation_s"])
        for r in result["rounds"]])
    csv_out("02_training/client_rounds.csv", [dict(round=r["round"], **client)
            for r in result["rounds"] for client in r["clients"]])

    torch.set_num_threads(1)
    test_rows = [r for r in all_rows if r["split"] == "test"]
    before = predictions(validate_envelope(checkpoint["initial_model"]), test_rows)
    after = predictions(validate_envelope(checkpoint["model"]), test_rows)
    initial_mae = sum(abs(p-r["target_ms"]) for p, r in zip(before, test_rows)) / len(test_rows)
    final_mae = sum(abs(p-r["target_ms"]) for p, r in zip(after, test_rows)) / len(test_rows)
    final_rmse = math.sqrt(sum((p-r["target_ms"])**2 for p, r in zip(after, test_rows)) / len(test_rows))
    saved = result["test"]["fl"]
    if saved["count"] != len(test_rows) or not math.isclose(final_mae, saved["mae_ms"], abs_tol=1e-6):
        raise ValueError("Recomputed test MAE does not match the saved experiment")
    if not math.isclose(final_rmse, saved["rmse_ms"], abs_tol=1e-6):
        raise ValueError("Recomputed test RMSE does not match the saved experiment")
    csv_out("03_prediction/test_predictions.csv", [dict(
        client_id=row["client_id"], link_id=row["link_id"], tick=row["tick"],
        observed_delay_ms=row["observed_delay_ms"], target_ms=row["target_ms"],
        initial_model_prediction_ms=pre, trained_model_prediction_ms=post,
        persistence_prediction_ms=row["observed_delay_ms"],
        initial_absolute_error_ms=abs(pre-row["target_ms"]),
        trained_absolute_error_ms=abs(post-row["target_ms"]))
        for row, pre, post in zip(test_rows, before, after)])
    csv_out("03_prediction/test_metrics.csv", [
        dict(model="initial_checkpoint_recomputed", count=len(test_rows), mae_ms=initial_mae,
             rmse_ms=math.sqrt(sum((p-r["target_ms"])**2 for p, r in zip(before, test_rows))/len(test_rows))),
        dict(model="trained_checkpoint_recomputed", count=len(test_rows), mae_ms=final_mae, rmse_ms=final_rmse),
        *[dict(model=name, **{k: v for k, v in value.items() if k != "by_layer"})
          for name, value in result["test"].items() if isinstance(value, dict) and "mae_ms" in value]])

    networks = {}
    summaries, flow_rows, route_rows = [], [], []
    for path in sorted((source / "network").glob("*.json")):
        network = json.loads(path.read_text(encoding="utf-8"))
        networks[path.stem] = network
        summaries.append(dict(policy=path.stem, **network["summary"]))
        flow_rows.extend(dict(policy=path.stem, **flow) for flow in network["flows"])
        route_rows.extend(dict(comparison_policy=path.stem, **event) for event in network["audit"])
    csv_out("04_routing/policy_metrics.csv", summaries)
    csv_out("04_routing/flows.csv", flow_rows)
    csv_out("04_routing/route_decisions.csv", route_rows)
    pairs = []
    for baseline in ("static-equal", "current-equal"):
        left = {flow["id"]: flow for flow in networks[baseline]["flows"]}
        right = {flow["id"]: flow for flow in networks["fl-equal"]["flows"]}
        if left.keys() != right.keys():
            raise ValueError("Network baseline and FL flow IDs differ")
        for key, original in left.items():
            selected = right[key]
            for field in ("source", "destination", "arrival", "size_mbit", "deadline_s"):
                if original[field] != selected[field]:
                    raise ValueError("Unpaired routing workload")
            def completion(flow):
                return flow["finished"] - flow["arrival"] if flow.get("finished") is not None else None
            a, b = completion(original), completion(selected)
            pairs.append(dict(flow_id=key, baseline_policy=baseline, fl_policy="fl-equal",
                source=original["source"], destination=original["destination"],
                size_mbit=original["size_mbit"], arrival_tick=original["arrival"],
                baseline_route_nodes=original["route_nodes"], fl_route_nodes=selected["route_nodes"],
                baseline_state=original["state"], fl_state=selected["state"],
                baseline_completion_s=a, fl_completion_s=b,
                fl_minus_baseline_completion_s=b-a if a is not None and b is not None else None))
    csv_out("04_routing/paired_flows.csv", pairs)
    for path in sorted((source / "network").glob("*.json")):
        target = destination / "04_routing" / "original_json" / path.name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(path, target)

    glossary = [
        ("client_id / link_id", "mã định danh", "Client giữ dữ liệu / link sinh telemetry"),
        ("source_run_id", "mã lần tạo dataset", "Nguồn dữ liệu bất biến, có thể được dùng lại cho nhiều experiment"),
        ("experiment_id / dataset_id", "mã định danh", "Liên kết tới experiment và dataset trong database gốc"),
        ("layer", "nhãn", "GROUND / AIR / SPACE / SEA"),
        ("history_valid", "boolean", "Đặc trưng lịch sử có đủ điều kiện sử dụng"),
        ("delta_delay_ms", "ms", "observed_delay_ms trừ previous_delay_ms"),
        ("observed_delay_ms", "ms", "Độ trễ payload tham chiếu tại t, đặc trưng đầu vào"),
        ("previous_delay_ms", "ms", "Độ trễ tại t-1; thay bằng hiện tại nếu lịch sử không hợp lệ"),
        ("target_ms", "ms", "Nhãn cùng link/payload tại t+1, chỉ dùng học/đánh giá"),
        ("available_mbps", "Mbps", "Băng thông còn lại tại t"),
        ("distance_km", "km", "Khoảng cách link mô phỏng"),
        ("propagation_ms", "ms", "Độ trễ lan truyền của link"),
        ("queue_ms", "ms", "Độ trễ hàng đợi mô phỏng tại t"),
        ("payload_bytes", "byte", "Kích thước payload tham chiếu"),
        ("load", "tỷ lệ", "Tải link tại t; load_before tại t-1; delta_load là hiệu"),
        ("tick", "bước mô phỏng", "Chỉ số thời gian, không là timestamp đo mạng thực"),
        ("split", "nhãn", "train / validation / test, phân chia theo thời gian có khoảng cách"),
        ("x / y", "độ", "Trong topology đã lưu: x là kinh độ, y là vĩ độ"),
        ("capacity_mbps", "Mbps", "Dung lượng danh định của link trong topology snapshot"),
        ("validation_mae_ms", "ms", "Sai số tuyệt đối trung bình trên validation tại vòng FL"),
        ("validation_rmse_ms", "ms", "Căn sai số bình phương trung bình trên validation tại vòng FL"),
        ("trained_absolute_error_ms", "ms", "Trị tuyệt đối của trained_model_prediction_ms trừ target_ms"),
        ("initial_absolute_error_ms", "ms", "Trị tuyệt đối của initial_model_prediction_ms trừ target_ms"),
        ("size_mbit", "Mbit", "Lượng dữ liệu yêu cầu của flow mô phỏng"),
        ("route_nodes", "danh sách node", "Tuyến cuối của flow, xem route_decisions.csv để đọc lịch sử đổi tuyến"),
        ("fl_minus_baseline_completion_s", "giây", "Thời gian hoàn tất FL trừ baseline; âm nghĩa là FL nhanh hơn"),
        ("initial_model_prediction_ms", "ms", "Suy luận lại checkpoint ban đầu trên cùng tập test"),
        ("trained_model_prediction_ms", "ms", "Suy luận lại checkpoint đã học; MAE/RMSE đối chiếu kết quả đã lưu"),
        ("mean_completion_s", "giây", "Thời gian hoàn tất flow trung bình, khác độ trễ link và MAE"),
        ("delivery_ratio", "tỷ lệ", "Chỉ số delivery_ratio lưu bởi bộ mô phỏng; không đồng nghĩa QoS"),
    ]
    csv_out("data_dictionary.csv", [dict(column=a, unit=b, meaning=c) for a, b, c in glossary])
    readme = f"""# Minh chứng dữ liệu đầu vào, huấn luyện và định tuyến

Experiment **#{experiment_id}**, dataset **#{dataset.id}**, seed **{runtime.seed}**.
Runtime: `{config['runtime']}`. Target: `{config['target']}`.
Mẫu: **{len(all_rows):,}**, client: **{len(clients)}**; split: {dict(counts)}.
Số vòng đã hoàn tất: **{len(result['rounds'])}**.

## Mở theo thứ tự

1. `01_input/nodes.csv`, `links.csv`, `topology.json`: topology snapshot đã dùng cho thí nghiệm, không lấy trạng thái địa cầu hiện tại.
2. `01_input/observations.csv`: toàn bộ mẫu được đọc lại từ MySQL từng client. `train.csv`, `validation.csv`, `test.csv` là ba phần tương ứng, không phải dữ liệu sinh mới.
3. `02_training/config.json`: cấu hình huấn luyện; `round_metrics.csv`: validation MAE/RMSE qua từng vòng; `client_rounds.csv`: client được chọn và thời gian/số mẫu học. File không có train loss nếu artifact gốc không ghi.
4. `03_prediction/test_predictions.csv`: cùng một mẫu test, so sánh dự đoán checkpoint ban đầu với checkpoint đã học và nhãn t+1. Hai cột observed/target là t/t+1, không phải trước/sau tối ưu.
5. `04_routing/policy_metrics.csv`: các đối chứng mạng. `paired_flows.csv`: cùng flow đầu vào, so sánh static-equal/current-equal với fl-equal, giữ cùng bộ cấp phát equal để đối chiếu tác động định tuyến. `route_decisions.csv`: quyết định tuyến theo tick; `flows.csv`: trạng thái kết thúc, tuyến cuối không đại diện toàn bộ lịch sử.
6. `data_dictionary.csv`: ý nghĩa và đơn vị của các cột chính. `manifest.json`: nguồn và SHA-256 của từng file để kiểm tra tính toàn vẹn.

## Nguồn và giới hạn

- Telemetry, tải, nhãn và workload mạng là **dữ liệu mô phỏng synthetic** theo code `sagsin/dataset.py`, `sagsin/topology.py`; không phải phép đo thực từ vệ tinh/UAV/tàu.
- Target của bộ này là độ trễ payload tham chiếu cùng link ở t+1; khác dataset #3 lịch sử có target model RTT. Không ghép hai bộ thành trước/sau.
- Công cụ export đọc raw data theo yêu cầu người vận hành để làm minh chứng. Đây là bước offline; không phải coordinator FL thu gom raw data trong quá trình học.
- Fingerprint từng client được kiểm tra trước khi xuất. Checkpoint chỉ được suy luận lại, **không huấn luyện lại**. Không sửa MySQL, checkpoint hoặc kết quả đã lưu.
- Trên {len(test_rows):,} mẫu test: MAE checkpoint ban đầu **{initial_mae:.9f} ms**, checkpoint đã học **{final_mae:.9f} ms**; MAE/RMSE sau học được kiểm tra khớp artifact gốc với sai số tuyệt đối tối đa 1e-6 ms.
- Sai số dự đoán thấp hơn không đảm bảo định tuyến tốt hơn; xem riêng từng chỉ số và đối chứng. Bộ này là một seed, không thay thế báo cáo nhiều seed.
- Không có mật khẩu, file .env hoặc cấu hình tài khoản trong gói xuất.

## Tạo lại một gói mới

Chạy từ thư mục gốc dự án, với MySQL và dữ liệu client còn nguyên:

```powershell
.\\.venv\\Scripts\\python.exe -m backend.export_evidence --experiment {experiment_id} --output storage/output/teaching_evidence/experiment-{experiment_id}-another-export
```

Thư mục đích phải chưa tồn tại. Các file CSV dùng UTF-8 BOM để mở bằng Excel.
"""
    (destination / "00_README.md").write_text(readme, encoding="utf-8")
    manifest = dict(experiment_id=experiment_id, dataset_id=dataset.id, seed=runtime.seed,
        source_run_id=source_run, runtime_id=config["runtime_id"], target=config["target"],
        created_at_utc=datetime.now(timezone.utc).isoformat(), data_origin="synthetic_simulation",
        source_artifacts=str(source.relative_to(ROOT)), client_fingerprints=fingerprints,
        validation=dict(client_fingerprints_verified=len(fingerprints), test_rows=len(test_rows),
                        checkpoint_test_mae_ms=final_mae, saved_test_mae_ms=saved["mae_ms"],
                        checkpoint_test_rmse_ms=final_rmse, saved_test_rmse_ms=saved["rmse_ms"],
                        routing_workloads_matched=True), files=[])
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            relative = path.relative_to(destination).as_posix()
            manifest["files"].append(dict(path=relative, bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), csv_rows=file_rows.get(relative)))
    write_json(destination / "manifest.json", manifest)
    print(f"Export complete: {destination}", flush=True)
    print(f"Verified test MAE {final_mae:.9f} ms; {len(all_rows)} observations; {len(manifest['files'])} files")
    return manifest


def csv_value(column, value):
    """Recover CSV scalars while preserving identifiers and structured values."""
    if value == "":
        return None
    if column in {"experiment_id", "dataset_id"}:
        return int(value)
    if column == "id" or column.endswith("_id"):
        return value
    if value in {"True", "False"}:
        return value == "True"
    if value.startswith(("[", "{")):
        return json.loads(value)
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
        return int(value)
    if re.fullmatch(r"-?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
        parsed = float(value)
        if math.isfinite(parsed):
            return parsed
    return value


def export_json_folder(source, destination):
    """Convert a verified CSV bundle into separate, typed JSON data files."""
    source = source.resolve()
    destination = destination.resolve()
    if source == destination or destination.is_relative_to(source):
        raise ValueError("Choose an output outside the verified source folder")
    original = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    verified_files = []
    for item in original["files"]:
        path = (source / item["path"]).resolve()
        if not path.is_relative_to(source):
            raise ValueError("Source manifest contains an invalid path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Source hash mismatch: {item['path']}")
        verified_files.append((item, path))
    destination.mkdir(parents=True, exist_ok=False)
    counts = {}
    for item, path in verified_files:
        relative = path.relative_to(source)
        if path.suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = [{key: csv_value(key, value) for key, value in row.items()}
                        for row in csv.DictReader(stream)]
            if len(rows) != item["csv_rows"]:
                raise ValueError(f"Source row count mismatch: {relative}")
            relative = relative.with_suffix(".json")
            write_json(destination / relative, rows)
            counts[relative.as_posix()] = len(rows)
        elif path.suffix == ".json":
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    readme = (source / "00_README.md").read_text(encoding="utf-8").replace(".csv", ".json")
    readme = readme.split("## Tạo lại một gói mới")[0]
    readme += """## Định dạng file

Mỗi loại dữ liệu nằm trong một file JSON riêng, giữ cấu trúc thư mục 01_input,
02_training, 03_prediction và 04_routing. Các file chuyển từ CSV là mảng object;
số là number, cờ là boolean, ô trống là null, tuyến là mảng node và mã định danh
được giữ là chuỗi. File JSON gốc được giữ nguyên nội dung.
Không gom toàn bộ dữ liệu vào một file lớn.

## Tạo lại gói JSON từ bản xuất đã kiểm chứng

```powershell
python -m backend.export_evidence --from-export storage/output/teaching_evidence/experiment-24-verified --output storage/output/teaching_evidence/a-new-json-export
```

Thư mục đích phải chưa tồn tại. JSON sử dụng UTF-8, có thể mở bằng VS Code.
`source_manifest.json` lưu manifest của gói CSV nguồn; `manifest.json` kiểm tra
các file JSON trong chính gói này. Bộ chuyển đổi không cần kết nối database.
"""
    (destination / "00_README.md").write_text(readme, encoding="utf-8")
    shutil.copy2(source / "manifest.json", destination / "source_manifest.json")
    manifest = {key: value for key, value in original.items()
                if key not in {"files", "created_at_utc"}}
    manifest.update(format="separate_json_files", source_export=source.name,
                    created_at_utc=datetime.now(timezone.utc).isoformat(), files=[])
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            relative = path.relative_to(destination).as_posix()
            if path.suffix == ".json":
                value = json.loads(path.read_text(encoding="utf-8"))
                if relative in counts and len(value) != counts[relative]:
                    raise ValueError("JSON row count differs after writing")
            manifest["files"].append(dict(path=relative, bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), records=counts.get(relative)))
    write_json(destination / "manifest.json", manifest)
    print(f"JSON export complete: {destination}")
    print(f"Converted {len(counts)} CSV tables; verified {len(verified_files)} source files")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--experiment", type=int)
    inputs.add_argument("--from-export", type=Path, help="Convert a verified export to separate JSON files")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.from_export:
        export_json_folder(args.from_export, args.output)
    else:
        export(args.experiment, args.output)


if __name__ == "__main__":
    main()
