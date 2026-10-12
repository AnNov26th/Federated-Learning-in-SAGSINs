"""Background worker for reproducible federated-learning experiments."""
import hashlib
import random
import time
from datetime import datetime, timezone

from backend.database.database import SessionLocal
from backend.models.network import Node
from backend.models.participant import Participant
from backend.models.simulation import Experiment, FLClientRound, FLRound, Metric
from backend.services.delay_service import estimate_communication_ms
from backend.services.scheduling_service import select_clients


PROFILE = {
    "normal": {"latency": 1.0, "bandwidth": 1.0},
    "high_latency": {"latency": 10.0, "bandwidth": 1.0},
    "low_bandwidth": {"latency": 1.0, "bandwidth": 0.1},
}


def _stable_seed(seed, round_number, client_id, purpose="train"):
    material = f"{seed}:{round_number}:{client_id}:{purpose}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big")


def _evaluate(model, dataset, batch_size):
    import torch
    from torch import nn
    from torch.utils.data import DataLoader
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    loss_fn = nn.CrossEntropyLoss(reduction="sum")
    total_loss = 0.0
    correct = 0
    count = 0
    model.eval()
    with torch.no_grad():
        for inputs, labels in loader:
            logits = model(inputs)
            total_loss += loss_fn(logits, labels).item()
            correct += (logits.argmax(dim=1) == labels).sum().item()
            count += labels.size(0)
    return correct / max(count, 1), total_loss / max(count, 1)


def _train_local(global_state, dataset, config, seed):
    import torch
    from torch import nn
    from torch.utils.data import DataLoader
    from backend.algorithms.mnist_model import MNISTCNN
    torch.manual_seed(seed)
    model = MNISTCNN()
    model.load_state_dict(global_state)
    loader = DataLoader(
        dataset, batch_size=config["batch_size"], shuffle=True, num_workers=0,
        generator=torch.Generator().manual_seed(seed),
    )
    optimizer = torch.optim.SGD(model.parameters(), lr=config["learning_rate"])
    loss_fn = nn.CrossEntropyLoss()
    started = time.perf_counter()
    model.train()
    for _ in range(config["local_epochs"]):
        for inputs, labels in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(inputs), labels)
            loss.backward()
            optimizer.step()
    elapsed = time.perf_counter() - started
    accuracy, loss = _evaluate(model, dataset, config["batch_size"])
    state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    return state, len(dataset), accuracy, loss, elapsed


def run_experiment(experiment_id):
    """Train an experiment, persisting every attempted round and its outcomes."""
    db = SessionLocal()
    try:
        import numpy as np
        import torch
        from backend.algorithms.fedavg import FedAvg
        from backend.algorithms.mnist_model import MNISTCNN
        from backend.utils.dataset_manager import MNISTDatasetManager

        experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
        if experiment is None:
            return
        config = dict(experiment.config_json or {})
        experiment.status = "RUNNING"
        experiment.started_at = datetime.now(timezone.utc)
        db.commit()

        seed = int(config["seed"])
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        manager = MNISTDatasetManager()
        train_dataset, test_dataset = manager.load_data()
        centralized = experiment.algorithm == "Centralized"
        candidate_ids = list(config.get("candidate_pool") or config.get("clients") or [])
        if centralized:
            partitions = [train_dataset]
            client_partition = {}
        elif config["partition"] == "non_iid":
            partitions = manager.partition_non_iid(len(candidate_ids), seed=seed)
            client_partition = dict(zip(candidate_ids, partitions))
        else:
            partitions = manager.partition_iid(len(candidate_ids), seed=seed)
            client_partition = dict(zip(candidate_ids, partitions))
        if not centralized and (not candidate_ids or any(len(partition) == 0 for partition in partitions)):
            raise ValueError("Each candidate client must receive at least one MNIST training sample.")

        if not centralized:
            participant_rows = db.query(Participant).filter(Participant.node_id.in_(candidate_ids)).all()
            sizes = {client_id: len(partition) for client_id, partition in client_partition.items()}
            for participant in participant_rows:
                participant.dataset_size = sizes.get(participant.node_id, 0)
            db.commit()

        global_model = MNISTCNN()
        global_state = {key: value.detach().cpu().clone() for key, value in global_model.state_dict().items()}
        network_profile = config.get("network_profile", "normal")
        profile = PROFILE[network_profile]
        model_bytes = sum(value.numel() * value.element_size() for value in global_state.values())
        model_mb = model_bytes / (1024 * 1024)
        nodes = {
            node.id: node for node in db.query(Node).filter(Node.id.in_(candidate_ids)).all()
        } if not centralized else {}
        if not centralized and len(nodes) != len(set(candidate_ids)):
            raise ValueError("A configured candidate node no longer exists.")
        snapshot = config.get("client_profiles") or {
            client_id: {
                "status": nodes[client_id].status,
                "latency": nodes[client_id].latency,
                "bandwidth": nodes[client_id].bandwidth,
            }
            for client_id in candidate_ids
        }
        selection_policy = config.get("selection_policy", "round_sample")
        failed_without_clients = False

        for round_number in range(1, experiment.rounds + 1):
            round_started = time.perf_counter()
            local_states, sample_counts, outcomes = [], [], []
            selected_comm_times, selected_latencies, selected_bandwidths = [], [], []
            if centralized:
                state, _, _, _, _ = _train_local(
                    global_state, train_dataset, config, _stable_seed(seed, round_number, "central", "train"),
                )
                global_state = state
                local_states.append(state)
                sample_counts.append(len(train_dataset))
            else:
                if "candidate_pool" in config and selection_policy == "round_sample":
                    client_ids = select_clients(
                        experiment.algorithm, candidate_ids, snapshot,
                        int(config.get("client_count", len(candidate_ids))), seed, round_number,
                        model_mb, network_profile,
                    )
                else:
                    # Backward compatibility for existing experiments that stored a fixed cohort.
                    client_ids = candidate_ids
                rngs = {client_id: random.Random(_stable_seed(seed, round_number, client_id, "dropout"))
                        for client_id in client_ids}
                for client_id in client_ids:
                    partition = client_partition[client_id]
                    client_profile = snapshot.get(client_id, {})
                    latency_ms = max(0.0, float(client_profile.get("latency", nodes[client_id].latency) or 0.0) * profile["latency"])
                    bandwidth_mbps = max(0.01, float(client_profile.get("bandwidth", nodes[client_id].bandwidth) or 0.01) * profile["bandwidth"])
                    communication_ms = estimate_communication_ms(
                        latency_ms, bandwidth_mbps, model_mb, network_profile="normal",
                    )
                    selected_latencies.append(latency_ms)
                    selected_bandwidths.append(bandwidth_mbps)
                    if rngs[client_id].random() < config["dropout_probability"]:
                        outcomes.append(FLClientRound(
                            client_id=client_id, status="DROPPED", samples_used=0,
                            training_duration_s=0, latency_ms=latency_ms, communication_time_ms=0,
                            data_transferred_mb=0, failure_reason="Simulated client dropout",
                        ))
                        continue
                    if communication_ms > config["timeout_ms"]:
                        timeout_elapsed_ms = float(config["timeout_ms"])
                        selected_comm_times.append(timeout_elapsed_ms)
                        outcomes.append(FLClientRound(
                            client_id=client_id, status="TIMEOUT", samples_used=0,
                            training_duration_s=0, latency_ms=latency_ms,
                            communication_time_ms=timeout_elapsed_ms, data_transferred_mb=0,
                            failure_reason="Estimated model transfer exceeded the configured timeout",
                        ))
                        continue
                    selected_comm_times.append(communication_ms)
                    state, samples, accuracy, loss, duration = _train_local(
                        global_state, partition, {
                            **config,
                            "local_epochs": int(config.get("local_epochs_by_client", {}).get(client_id, config["local_epochs"])),
                        },
                        _stable_seed(seed, round_number, client_id, "train"),
                    )
                    local_states.append(state)
                    sample_counts.append(samples)
                    outcomes.append(FLClientRound(
                        client_id=client_id, status="COMPLETED", samples_used=samples,
                        local_accuracy=accuracy, local_loss=loss, training_duration_s=duration,
                        latency_ms=latency_ms, communication_time_ms=communication_ms,
                        data_transferred_mb=2 * model_mb,
                    ))

            if local_states and not centralized:
                global_state = FedAvg.aggregate(local_states, sample_counts)
            global_model.load_state_dict(global_state)
            accuracy, loss = _evaluate(global_model, test_dataset, config["batch_size"])
            if centralized:
                round_duration_s = time.perf_counter() - round_started
            else:
                round_duration_s = max((
                    (outcome.training_duration_s if outcome.status == "COMPLETED" else 0.0)
                    + outcome.communication_time_ms / 1000 for outcome in outcomes
                ), default=0.0)
            fl_round = FLRound(
                experiment_id=experiment.id, round=round_number,
                participants_count=len(local_states) if not centralized else 0,
                accuracy=accuracy, loss=loss, round_duration_s=round_duration_s,
            )
            db.add(fl_round)
            db.flush()
            for outcome in outcomes:
                outcome.round_id = fl_round.id
            db.add_all(outcomes)
            db.add(Metric(
                round_id=fl_round.id,
                latency_ms=float(np.mean(selected_latencies)) if selected_latencies else 0.0,
                communication_time_ms=max(selected_comm_times, default=0.0),
                energy_j=max(0.0, round_duration_s * 10.0),
                bandwidth_mbps=float(np.mean(selected_bandwidths)) if selected_bandwidths else 0.0,
                data_transferred_mb=sum(outcome.data_transferred_mb for outcome in outcomes),
                # Packet loss is not modeled; client dropout/timeout is exposed separately.
                packet_loss_ratio=0.0,
            ))
            db.commit()
            if not centralized and not local_states:
                failed_without_clients = True
                experiment.error_message = f"Round {round_number}: no clients completed training."
                experiment.status = "FAILED"
                experiment.completed_at = datetime.now(timezone.utc)
                db.commit()
                break

        if not failed_without_clients:
            experiment.status = "COMPLETED"
            experiment.completed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as exc:
        db.rollback()
        failed = db.query(Experiment).filter(Experiment.id == experiment_id).first()
        if failed:
            failed.status = "FAILED"
            failed.error_message = str(exc)[:500]
            failed.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
