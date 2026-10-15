"""Federated regression: client partitions -> model -> scheduling -> outcomes.

Synthetic labels are simulator ground truth, not real-world measurements. Raw
rows stay in logical per-client partitions; aggregation consumes only weights.
"""
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from backend.algorithms.fedavg import FedAvg
from backend.algorithms.network_delay_model import NetworkDelayRegressor, checkpoint, encode_features, predict
from backend.models.network_learning import NetworkDataset, NetworkObservation, NetworkRoundEvaluation, NetworkRoundPrediction
from backend.models.simulation import FLClientRound, FLRound, Metric
from backend.models.participant import Participant
from backend.services.delay_service import estimate_communication_ms
from backend.services.network_dataset_service import stable_seed
from backend.services.scheduling_service import select_clients


@dataclass(frozen=True)
class ObservationSample:
    id: int
    client_id: str
    sequence: int
    split: str
    features_json: dict
    target_delay_ms: float


def as_tensors(rows):
    return TensorDataset(
        torch.tensor([encode_features(row.features_json) for row in rows], dtype=torch.float32),
        torch.tensor([math.log1p(row.target_delay_ms) for row in rows], dtype=torch.float32),
    )


def evaluate(model, rows):
    predictions = predict(model, [row.features_json for row in rows])
    targets = [row.target_delay_ms for row in rows]
    errors = [prediction - target for prediction, target in zip(predictions, targets)]
    mean = sum(targets) / len(targets)
    ss_total = sum((value - mean) ** 2 for value in targets)
    ss_error = sum(error ** 2 for error in errors)
    return {
        "mae_ms": sum(abs(error) for error in errors) / len(errors),
        "rmse_ms": math.sqrt(ss_error / len(errors)),
        "r2": 1 - ss_error / ss_total if ss_total > 1e-12 else None,
        "loss": sum((math.log1p(max(0, p)) - math.log1p(t)) ** 2 for p, t in zip(predictions, targets)) / len(targets),
    }


def train_local(global_state, rows, config, seed):
    torch.manual_seed(seed)
    model = NetworkDelayRegressor()
    model.load_state_dict(global_state)
    loader = DataLoader(as_tensors(rows), batch_size=config["batch_size"], shuffle=True,
                        generator=torch.Generator().manual_seed(seed))
    optimizer = torch.optim.SGD(model.parameters(), lr=config["learning_rate"])
    started = time.perf_counter()
    model.train()
    for _ in range(config["local_epochs"]):
        for inputs, targets in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = nn.functional.mse_loss(model(inputs), targets)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
    elapsed = time.perf_counter() - started
    return {key: value.detach().clone() for key, value in model.state_dict().items()}, evaluate(model, rows)["loss"], elapsed


def run_network_experiment(db, experiment):
    config = dict(experiment.config_json)
    dataset = db.get(NetworkDataset, config["dataset_id"])
    if dataset is None:
        raise ValueError("The configured network dataset no longer exists.")
    candidate_ids = sorted(config["candidate_pool"])
    grouped = defaultdict(lambda: defaultdict(list))
    rows = db.query(NetworkObservation).filter(
        NetworkObservation.dataset_id == dataset.id, NetworkObservation.client_id.in_(candidate_ids),
    ).order_by(NetworkObservation.sequence).all()
    for row in rows:
        # Snapshot scalar values before commits expire SQLAlchemy instances.
        # Evaluating held-out samples must not cause a query per sample/round.
        grouped[row.client_id][row.split].append(ObservationSample(
            row.id, row.client_id, row.sequence, row.split, dict(row.features_json), row.target_delay_ms,
        ))
    if any(not grouped[client][split] for client in candidate_ids for split in ("train", "validation", "online", "test")):
        raise ValueError("Each candidate needs complete train/validation/online/test partitions.")
    if any(len(grouped[client]["online"]) < experiment.rounds for client in candidate_ids):
        raise ValueError("Not enough online observations for the requested rounds.")
    seed = config["seed"]
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    model = NetworkDelayRegressor()
    test_rows = [row for client in candidate_ids for row in grouped[client]["test"]]
    validation_rows = [row for client in candidate_ids for row in grouped[client]["validation"]]
    persistence_mae = sum(abs(row.features_json["observed_delay_ms"] - row.target_delay_ms) for row in test_rows) / len(test_rows)
    profiles = config["client_profiles"]
    model_mb = dataset.config_json["payload_bytes"] / (1024 * 1024)
    # These buffers are per client; only that client's completed online samples
    # are appended, and only after its scheduling decision and transfer outcome.
    local_rows = {client: list(grouped[client]["train"]) for client in candidate_ids}
    for participant in db.query(Participant).filter(Participant.node_id.in_(candidate_ids)).all():
        participant.dataset_size = len(local_rows[participant.node_id])
    db.commit()

    for round_number in range(1, experiment.rounds + 1):
        started = time.perf_counter()
        observations = {client: grouped[client]["online"][round_number - 1] for client in candidate_ids}
        estimates = dict(zip(candidate_ids, predict(model, [observations[client].features_json for client in candidate_ids])))
        centralized = experiment.algorithm == "Centralized"
        cold_start = experiment.algorithm == "Predictive" and round_number == 1
        if centralized:
            selected = []
            selection_source = "centralized_control"
        elif experiment.algorithm == "Predictive" and not cold_start:
            selected = select_clients("Predictive", candidate_ids, profiles, config["client_count"], seed,
                                      round_number, model_mb, config["network_profile"], predicted_delays=estimates)
            selection_source = "global_model_previous_round"
        else:
            selected = select_clients("FedAvg" if cold_start else experiment.algorithm, candidate_ids, profiles,
                                      config["client_count"], seed, round_number, model_mb, config["network_profile"])
            selection_source = "random_cold_start" if cold_start else "uniform_random" if experiment.algorithm == "FedAvg" else "static_profile"
        global_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
        states, sizes, outcomes = [], [], []
        if centralized:
            central_rows = [row for client in candidate_ids for row in local_rows[client]]
            state, _, _ = train_local(global_state, central_rows, config, stable_seed(seed, round_number, "central"))
            model.load_state_dict(state)
        for client in selected:
            observation = observations[client]
            actual_ms = observation.target_delay_ms  # revealed after selection
            dropout = random.Random(stable_seed(seed, client, f"dropout-{round_number}")).random() < config["dropout_probability"]
            status = "DROPPED" if dropout else "TIMEOUT" if actual_ms > config["timeout_ms"] else "COMPLETED"
            state, loss, duration = None, None, 0.
            if status == "COMPLETED":
                state, loss, duration = train_local(global_state, local_rows[client], {
                    **config, "local_epochs": config.get("local_epochs_by_client", {}).get(client, config["local_epochs"]),
                }, stable_seed(seed, client, f"train-{round_number}"))
                states.append(state)
                sizes.append(len(local_rows[client]))
            outcomes.append(FLClientRound(
                client_id=client, status=status, samples_used=len(local_rows[client]) if state else 0,
                local_accuracy=None, local_loss=loss, training_duration_s=duration,
                latency_ms=observation.features_json["latency_ms"],
                communication_time_ms=0 if dropout else min(actual_ms, config["timeout_ms"]),
                data_transferred_mb=2 * model_mb if state else 0,
                failure_reason=None if state else "Simulated dropout" if dropout else "Simulator transfer exceeded timeout",
            ))
        if states:
            model.load_state_dict(FedAvg.aggregate(states, sizes))
        quality = evaluate(model, test_rows)
        validation = evaluate(model, validation_rows)
        round_duration = time.perf_counter() - started if centralized else max(
            (row.training_duration_s + row.communication_time_ms / 1000 for row in outcomes), default=0,
        )
        saved_round = FLRound(experiment_id=experiment.id, round=round_number, participants_count=len(states),
                              accuracy=0., loss=quality["loss"], round_duration_s=round_duration)
        db.add(saved_round)
        db.flush()
        for outcome in outcomes:
            outcome.round_id = saved_round.id
        db.add_all(outcomes)
        selected_rows = [observations[client] for client in selected]
        db.add(Metric(round_id=saved_round.id,
                      latency_ms=sum(row.features_json["latency_ms"] for row in selected_rows) / max(1, len(selected_rows)),
                      communication_time_ms=max((outcome.communication_time_ms for outcome in outcomes), default=0),
                      energy_j=round_duration * 10, bandwidth_mbps=sum(row.features_json["bandwidth_mbps"] for row in selected_rows) / max(1, len(selected_rows)),
                      data_transferred_mb=sum(outcome.data_transferred_mb for outcome in outcomes),
                      packet_loss_ratio=sum(row.features_json["packet_loss_ratio"] for row in selected_rows) / max(1, len(selected_rows))))
        db.add(NetworkRoundEvaluation(round_id=saved_round.id, mae_ms=quality["mae_ms"], rmse_ms=quality["rmse_ms"],
                                      r2=quality["r2"], validation_mae_ms=validation["mae_ms"],
                                      persistence_mae_ms=persistence_mae, test_samples=len(test_rows),
                                      selection_source=selection_source, checkpoint_json=checkpoint(model)))
        for client in candidate_ids:
            db.add(NetworkRoundPrediction(
                round_id=saved_round.id, client_id=client, observation_id=observations[client].id,
                predicted_delay_ms=estimates[client], observed_delay_ms=observations[client].target_delay_ms if client in selected else None,
                rule_delay_ms=estimate_communication_ms(profiles[client]["latency"], profiles[client]["bandwidth"], model_mb, config["network_profile"]),
                selected=client in selected, model_round=round_number - 1,
            ))
        db.commit()
        # Only completed clients reveal a new local training example. No test
        # row is ever inserted into these buffers; test occurs after all online ticks.
        for outcome in outcomes:
            if outcome.status == "COMPLETED":
                local_rows[outcome.client_id].append(observations[outcome.client_id])
        if not centralized and not states:
            raise ValueError(f"Round {round_number}: no clients completed training.")
