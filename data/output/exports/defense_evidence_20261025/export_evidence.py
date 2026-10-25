"""Extract presentation evidence from existing exports; never access the database.

Dataset 3 samples and experiment 2 results are separate evidence sources.
No training, checkpoint reconstruction, or simulated audit is performed here.
"""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(name, rows):
    if rows:
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main():
    metadata_path = "data/exports/network_dataset_3_20261023/metadata.json"
    observations_path = "data/exports/network_dataset_3_20261023/observations.csv"
    result_path = "data/database_backups/training-topology-20261023-result.json"
    request_path = "data/database_backups/latest-training-request.json"
    metadata = read_json(metadata_path)
    report = read_json(result_path)
    request = read_json(request_path)
    with (ROOT / observations_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == metadata["row_count"]
    assert {int(row["dataset_id"]) for row in rows} == {metadata["dataset_id"]}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["client_id"], row["split"]].append(row)
    boundaries = []
    for (client, split), values in sorted(grouped.items()):
        sequences = [int(row["sequence"]) for row in values]
        boundaries.append(dict(dataset_id=metadata["dataset_id"], client_id=client,
                               split=split, count=len(values), first_sequence=min(sequences),
                               last_sequence=max(sequences)))
    write_csv("dataset3_temporal_boundaries.csv", boundaries)
    profiles = metadata["config"]["profiles"]
    write_csv("dataset3_client_profiles.csv", [dict(client_id=client, **profile)
                                               for client, profile in profiles.items()])
    # One client per layer, first two observations in each temporal split.
    clients = {}
    for client, profile in profiles.items():
        clients.setdefault(profile["layer"], client)
    samples = []
    for layer, client in sorted(clients.items()):
        for split in metadata["config"]["split_order"]:
            samples.extend(sorted(grouped[client, split], key=lambda row: int(row["sequence"]))[:2])
    write_csv("dataset3_samples_by_layer_and_split.csv", samples)
    pairs = []
    indexed = {(row["client_id"], row["split"], int(row["sequence"])): row for row in rows}
    for row in samples:
        following = indexed.get((row["client_id"], row["split"], int(row["sequence"]) + 1))
        if following:
            difference = abs(float(row["target_delay_ms"]) - float(following["observed_delay_ms"]))
            pairs.append(dict(client_id=row["client_id"], split=row["split"],
                              sequence_t=row["sequence"], observation_id=row["observation_id"],
                              current_delay_ms=row["observed_delay_ms"], target_delay_ms=row["target_delay_ms"],
                              next_observation_id=following["observation_id"],
                              next_current_delay_ms=following["observed_delay_ms"],
                              absolute_difference_ms=difference))
            assert difference < 0.001, "Unexpected discrepancy in exported next-tick targets"
    write_csv("dataset3_next_tick_pairs.csv", pairs)
    write_json("experiment2_training_request.json", request)
    write_json("experiment2_metrics_from_saved_report.json", {
        "source_file": result_path,
        "evidence_type": "extracted_saved_report_not_live_database_verification",
        **{key: value for key, value in report.items() if key != "ocean_route"},
        "mae_improvement_ms": report["model"]["persistence_mae_ms"] - report["model"]["mae_ms"],
        "mae_improvement_percent": 100 * (report["model"]["persistence_mae_ms"] - report["model"]["mae_ms"]) / report["model"]["persistence_mae_ms"],
    })
    write_json("experiment2_saved_route_response.json", report["ocean_route"])
    route_rows = []
    for policy in ("route", "baseline"):
        route = report["ocean_route"][policy]
        route_rows.append(dict(policy=policy, path=" -> ".join(route["path"]),
                               cost=route["cost"], total_predicted_transfer_ms=route["total_predicted_transfer_ms"],
                               total_static_transfer_ms=route["total_static_transfer_ms"],
                               application_one_way_ms=route["application"]["estimated_one_way_ms"],
                               application_budget_ms=route["application"]["latency_budget_ms"],
                               application_budget_met=route["application"]["latency_budget_met"],
                               estimated_hops=route["estimated_hops"]))
    write_csv("experiment2_route_comparison.csv", route_rows)
    sources = []
    for relative in (metadata_path, observations_path, result_path, request_path):
        path = ROOT / relative
        sources.append(dict(path=relative, bytes=path.stat().st_size,
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    write_json("manifest.json", {
        "method": "Read existing files only; derived tables preserve source values.",
        "sources": sources,
        "dataset3": dict(id=metadata["dataset_id"], scenario_id=metadata["scenario_id"],
                         observation_count=len(rows), client_count=len(profiles), config={
                             key: value for key, value in metadata["config"].items() if key != "profiles"}),
        "experiment2": dict(id=report["experiment_id"], dataset_id=report["dataset_id"]),
        "limitations": [
            "Dataset 3 is not the training dataset of experiment 2; do not present them as one run.",
            "Main database connection was unavailable during this preparation.",
            "No checkpoint tensors, per-round scheduler audits or local model updates were available in these source files.",
            "No matched three-policy benchmark or IID comparison results were available in these source files.",
            "Saved routing output reflects its historical implementation; reproduce on the current application separately.",
            "CSV target values have export precision rounding; next-tick pair checks use 0.001 ms tolerance.",
        ],
    })
    print(json.dumps(dict(observations=len(rows), clients=len(profiles), sample_rows=len(samples),
                          next_tick_pairs=len(pairs), output=str(OUT)), ensure_ascii=True))


if __name__ == "__main__":
    main()
