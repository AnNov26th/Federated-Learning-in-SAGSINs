"""Explicit offline centralized benchmark. Never imported by the FL coordinator.

Reads local stores on the benchmark host with the operator's filesystem access.
This is a separate experimental counterfactual, not the federated protocol.
"""
import argparse
import csv
import json
import math
import struct
import zlib
from pathlib import Path
import torch
from .config import ExperimentConfig
from .dataset import load_local
from .database import credentials
from .model import DelayModel, encode, errors, metrics, predictions, train, validate_envelope
from .storage import read_json, write_json


def centralized(directory):
    directory = Path(directory)
    result = read_json(directory / "result.json")
    checkpoint = read_json(directory / "checkpoint.json")
    config = ExperimentConfig.from_saved(result["config"])
    torch.set_num_threads(1)
    model = validate_envelope(checkpoint["initial_model"])
    train_rows, test_rows = [], []
    raw_bytes = 0
    secrets_value = credentials()
    for identifier in result["clients"]:
        settings = secrets_value["clients"][identifier]
        rows = load_local(settings, directory.name, "train")
        train_rows.extend(rows)
        test_rows.extend(load_local(settings, directory.name, "test"))
        raw_bytes += len(json.dumps(rows, separators=(",", ":"), allow_nan=False).encode())
    budget = sum(c.get("samples", 0) * c.get("local_epochs",config.local_epochs) for r in result["rounds"] for c in r["clients"] if c["status"] == "completed")
    remaining, epoch = budget, 0
    while remaining:
        subset = train_rows[:min(remaining, len(train_rows))]
        train(model, subset, 1, config.learning_rate, config.batch_size, config.seed + epoch, config.optimizer, config.loss)
        remaining -= len(subset)
        epoch += 1
    quality = metrics([errors(predictions(model, test_rows), test_rows)])
    train_bytes = sum(value["sent_bytes"] + value["received_bytes"] for key, value in result["communication"]["categories"].items() if key in {"training", "startup", "control"})
    summary = {"centralized": quality, "centralized_sample_presentations": budget,
               "fl_sample_presentations": budget, "raw_training_json_bytes_once": raw_bytes,
               "fl_training_json_bytes": train_bytes,
               "fl_all_json_bytes": result["communication"]["total_json_bytes"],
               "savings_training_fraction": 1 - train_bytes / raw_bytes if raw_bytes else None,
               "savings_inclusive_fraction": 1 - result["communication"]["total_json_bytes"] / raw_bytes if raw_bytes else None,
               "model_family":config.model_family,"transport_codec":config.transport_codec,
               "notes": ["Offline benchmark reads client data explicitly; not part of FL server",
                         "Same train/test rows and model initialization; matched sample presentations",
                         "Bytes compare canonical JSON bodies; no TCP/TLS/header overhead",
                         "One-time dataset; no claim about continuous-stream break-even"]}
    write_json(directory / "offline-baseline.json", summary)
    return refresh_byte_baselines(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--bytes-only", action="store_true",help="Refresh codec-fair raw-data byte baselines without retraining")
    args = parser.parse_args()
    result=refresh_byte_baselines(args.run_directory) if args.bytes_only else centralized(args.run_directory)
    print(json.dumps(result, indent=2))


def refresh_byte_baselines(directory):
    """Post-hoc accounting only: no training, test selection or raw-data export."""
    directory=Path(directory)
    result=read_json(directory/"result.json")
    baseline=read_json(directory/"offline-baseline.json")
    accounts=credentials()["clients"]
    sizes={"raw_json":0,"raw_json_zlib":0,"training_float32":0,"training_float32_zlib":0}
    for client in result["clients"]:
        rows=load_local(accounts[client],directory.name,"train")
        plain=json.dumps(rows,separators=(",",":"),allow_nan=False).encode()
        flat=[number for row in rows for number in [*encode(row),math.log1p(row["target_ms"])]]
        binary=struct.pack(f"<{len(flat)}f",*flat)
        sizes["raw_json"]+=len(plain)
        sizes["raw_json_zlib"]+=len(zlib.compress(plain,6))
        sizes["training_float32"]+=len(binary)
        sizes["training_float32_zlib"]+=len(zlib.compress(binary,6))
    total=result["communication"]["total_json_bytes"]
    baseline["one_time_upload_bytes"]=sizes
    baseline["inclusive_savings_by_baseline"]={key:1-total/value if value else None for key,value in sizes.items()}
    baseline["byte_baseline_protocol"]="Per-client one-time bodies; raw JSON or lossless zlib; encoded training features/log targets float32 or lossless zlib; excludes all HTTP/TCP/TLS headers on both sides"
    write_json(directory/"offline-baseline.json",baseline)
    return baseline


if __name__ == "__main__":
    main()
