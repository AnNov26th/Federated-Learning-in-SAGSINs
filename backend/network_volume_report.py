"""Verify completed paired runs and export a readable HTML report and inference CSV."""
import argparse
import csv
import html
import json
import sqlite3
import os
from pathlib import Path

from backend.algorithms.network_delay_model import load_checkpoint, predict
from backend.network_volume_demo import csv_file, dump, benchmark_inputs


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    out = args.directory.resolve()
    inputs = benchmark_inputs(out)
    input_href = html.escape(Path(os.path.relpath(inputs, out)).as_posix(), quote=True)
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    runs = read_csv(out / "runs.csv")
    expected = len(manifest["profiles"]) * len(manifest["seeds"]) * 2
    if len(runs) != expected or not (out / "aggregates.csv").exists():
        raise ValueError(f"Expected {expected} completed runs and aggregates; found {len(runs)}.")
    connection = sqlite3.connect((out / "demo.sqlite").as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    checks, inferences, selections = [], [], []
    for profile in manifest["profiles"]:
        for seed in manifest["seeds"]:
            pair_dir = out / f"{profile}_seed{seed}"
            pair = {row["condition"]: row for row in runs if row["profile"] == profile and int(row["seed"]) == seed}
            small_id, large_id = (int(pair[key]["dataset_id"]) for key in ("small", "large"))
            for split in ("validation", "online", "test"):
                query = """SELECT COUNT(*) FROM (
                    SELECT client_id, sequence, features_json, target_delay_ms FROM network_observations WHERE dataset_id=? AND split=?
                    EXCEPT
                    SELECT client_id, sequence, features_json, target_delay_ms FROM network_observations WHERE dataset_id=? AND split=?)"""
                assert connection.execute(query, (small_id, split, large_id, split)).fetchone()[0] == 0
                assert connection.execute(query, (large_id, split, small_id, split)).fetchone()[0] == 0
            for condition, expected_count in (("small", 192), ("large", 1200)):
                counts = connection.execute("SELECT client_id,COUNT(*) FROM network_observations WHERE dataset_id=? AND split='train' GROUP BY client_id",
                                            (int(pair[condition]["dataset_id"]),)).fetchall()
                assert len(counts) == manifest["candidate_clients"]
                assert all(row[1] == expected_count for row in counts)
            assert connection.execute("""SELECT COUNT(*) FROM (
                SELECT client_id,sequence,features_json,target_delay_ms FROM network_observations WHERE dataset_id=? AND split='train'
                EXCEPT SELECT client_id,sequence,features_json,target_delay_ms FROM network_observations WHERE dataset_id=? AND split='train')""",
                (small_id, large_id)).fetchone()[0] == 0
            clients = connection.execute("SELECT type,MIN(id) client_id FROM nodes GROUP BY type ORDER BY type").fetchall()
            examples = [connection.execute("SELECT * FROM network_observations WHERE dataset_id=? AND client_id=? AND split='test' ORDER BY sequence LIMIT 1",
                                            (large_id, client["client_id"])).fetchone() for client in clients]
            for condition in ("small", "large"):
                saved = json.loads((pair_dir / f"{condition}_checkpoint.json").read_text(encoding="utf-8"))
                model = load_checkpoint(saved["state_dict"])
                assert sum(value.numel() for value in model.parameters()) == 961
                features = [json.loads(row["features_json"]) for row in examples]
                predictions = predict(model, features)
                for row, feature, prediction in zip(examples, features, predictions):
                    inferences.append(dict(profile=profile, seed=seed, condition=condition,
                        experiment_id=saved["experiment_id"], model_round=saved["round"],
                        source_observation_id=row["id"], client_id=row["client_id"], sequence=row["sequence"],
                        **feature, target_delay_ms=row["target_delay_ms"], predicted_delay_ms=prediction,
                        absolute_error_ms=abs(prediction-row["target_delay_ms"])))
            details = {condition: json.loads((pair_dir / f"{condition}_experiment.json").read_text(encoding="utf-8"))
                       for condition in ("small", "large")}
            changed_rounds = 0
            for small_round, large_round in zip(details["small"]["rounds"], details["large"]["rounds"]):
                small_selected = {item["client_id"] for item in small_round["predictions"] if item["selected"]}
                large_selected = {item["client_id"] for item in large_round["predictions"] if item["selected"]}
                changed_rounds += small_selected != large_selected
            selections.append(dict(profile=profile, seed=seed, rounds_with_different_selected_clients=changed_rounds,
                                   small_communication_ms=float(pair["small"]["total_communication_ms"]),
                                   large_communication_ms=float(pair["large"]["total_communication_ms"])))
            checks.append(dict(profile=profile, seed=seed, identical_validation_online_test=True,
                               small_train_is_subset=True, checkpoint_parameters=961))
    connection.close()
    csv_file(out / "checkpoint_inference_examples.csv", inferences)
    csv_file(out / "selection_comparison.csv", selections)
    dump(out / "verification.json", {"paired_conditions": checks, "completed_experiments": len(runs),
                                      "inference_examples": len(inferences), "passed": True})
    aggregates = read_csv(out / "aggregates.csv")
    table = []
    for profile in manifest["profiles"]:
        pair = {row["condition"]: row for row in aggregates if row["profile"] == profile}
        small, large = (float(pair[key]["mae_ms_mean"]) for key in ("small", "large"))
        table.append(dict(profile=profile, small_mae_ms=small, large_mae_ms=large,
                          persistence_mae_ms=float(pair["large"]["persistence_mae_ms_mean"]),
                          mae_reduction_percent=100*(small-large)/small,
                          small_std=float(pair["small"]["mae_ms_std"]), large_std=float(pair["large"]["mae_ms_std"])))
    dump(out / "summary.json", table)
    rows = "".join(f"<tr><th>{html.escape(row['profile'])}</th><td>{row['small_mae_ms']:.5f} ± {row['small_std']:.5f}</td>"
                   f"<td>{row['large_mae_ms']:.5f} ± {row['large_std']:.5f}</td><td>{row['persistence_mae_ms']:.5f}</td>"
                   f"<td>{row['mae_reduction_percent']:+.3f}%</td></tr>" for row in table)
    content = """<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Demo dữ liệu FL: 192 và 1.200 mẫu train/client</title><style>
body{font:16px/1.6 system-ui,sans-serif;max-width:1120px;margin:40px auto;padding:0 20px;color:#182433;background:#f5f7fa}
section{background:white;border:1px solid #dbe2ea;border-radius:12px;padding:24px;margin:20px 0}h1{line-height:1.3}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px;border-bottom:1px solid #dbe2ea;text-align:left}
.scroll{overflow:auto}a{color:#1254b0}code{overflow-wrap:anywhere}li{margin:8px 0}</style>
<h1>Ảnh hưởng của lượng dữ liệu và biến động mạng</h1>
<p>Kiến trúc giữ nguyên: 12 → 32 → 16 → 1; 961 tham số, 3.844 byte FP32.</p>
<section><h2>Cách so sánh</h2><p>178 client, chọn 24 client/vòng, 10 vòng, 2 local epochs, LR 0,01, batch 64, Non-IID.
Ba seed: 11, 42, 71. Cả hai điều kiện dùng cùng validation 400, online 100, test 400 mẫu/client.
Mức lớn sinh 2.000 mẫu lịch sử/client: 1.200 train + 400 validation + 400 test.
Mức nhỏ giữ 192 mẫu train gần nhất của chính chuỗi đó. Đây là ngân sách train tương ứng cấu hình 320 lịch sử,
nhưng giữ nguyên holdout lớn nên KHÔNG phải dataset chuẩn 320 mẫu lịch sử.</p>
<p>Toàn pool: 34.176 so với 213.600 mẫu train ban đầu. Vòng đầu nếu cả 24 client hoàn tất: 4.608 so với 28.800 mẫu.
Mức lớn sử dụng nhiều mẫu huấn luyện hơn; kiến trúc và số chiều đầu ra không thay đổi.</p></section>
<section><h2>MAE cuối vòng 10, trung bình ± độ lệch chuẩn qua ba seed</h2><div class="scroll"><table>
<thead><tr><th>Chế độ</th><th>192 train/client (ms)</th><th>1.200 train/client (ms)</th><th>Persistence (ms)</th><th>Giảm MAE khi tăng dữ liệu</th></tr></thead><tbody>""" + rows + f"""</tbody></table></div>
<p>Phần trăm dương: MAE mức lớn thấp hơn. Phần trăm âm: MAE mức lớn cao hơn. Không chọn checkpoint theo test.</p></section>
<section><h2>Chế độ mạng</h2><ul><li>normal: tải nền có tương quan theo thời gian.</li>
<li>bursty_congestion: đợt nghẽn 8/47 tick, tăng latency/tải/loss, giảm bandwidth.</li>
<li>regime_switching: luân phiên trạng thái nền và suy giảm mỗi 60 tick.</li></ul>
<p>Đây là giả định simulator. Predictor không được đưa nhãn tương lai hoặc lịch chuyển trạng thái vào input.</p></section>
<section><h2>File minh chứng</h2><ul><li><a href="runs.csv">Từng lần chạy</a> · <a href="paired_differences.csv">Chênh lệch từng seed</a> · <a href="round_metrics.csv">Metric từng vòng</a></li>
<li><a href="checkpoint_inference_examples.csv">Input/target/prediction suy luận lại từ checkpoint</a> · <a href="selection_comparison.csv">So sánh client được chọn và chi phí truyền</a></li>
<li><a href="verification.json">Kiểm chứng holdout giống nhau, train subset và model 961 tham số</a></li>
<li><a href="{input_href}/manifest.json">Cấu hình và giới hạn</a> · <a href="{input_href}/nodes.csv">Nodes</a> · <a href="{input_href}/links.csv">Links</a></li></ul>
<p><a href="{input_href}/">Input</a> chứa source_observations.csv, metadata và request theo profile_seed. Output chứa experiment, decision audit, client outcomes và checkpoint.
Metadata của mức nhỏ ghi quy tắc lọc để tái tạo chính xác từ CSV nguồn.</p></section>
<section><h2>Giới hạn kết luận</h2><p>Đây là demo trên một topology và dữ liệu tổng hợp. Tăng dữ liệu đồng thời tăng số bước tối ưu khi giữ cùng epochs;
không phải phép so sánh cùng ngân sách tính toán. Predictor có thể không thắng persistence, nhất là ở điểm chuyển trạng thái.
Không suy ra cải thiện mạng thực, khả năng tổng quát sang profile chưa học hoặc ý nghĩa thống kê chỉ từ ba seed.</p></section></html>"""
    (out / "report.html").write_text(content, encoding="utf-8")
    print(json.dumps({"verification_passed": True, "runs": len(runs), "report": str(out / "report.html"), "summary": table}, ensure_ascii=False))


if __name__ == "__main__":
    main()
