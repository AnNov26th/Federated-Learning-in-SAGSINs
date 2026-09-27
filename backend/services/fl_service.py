"""Background worker for reproducible MNIST FedAvg experiments."""
import random
import time

from backend.database.database import SessionLocal
from backend.models.network import Node
from backend.models.participant import Participant
from backend.models.simulation import Experiment, FLClientRound, FLRound, Metric


PROFILE = {
    "normal": {"latency": 1.0, "bandwidth": 1.0},
    "high_latency": {"latency": 10.0, "bandwidth": 1.0},
    "low_bandwidth": {"latency": 1.0, "bandwidth": 0.1},
}


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
        dataset,
        batch_size=config["batch_size"],
        shuffle=True,
        num_workers=0,
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
    """Train a single experiment, saving each completed round for live progress."""
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
        from datetime import datetime, timezone
        experiment.started_at = datetime.now(timezone.utc)
        db.commit()

        seed = int(config["seed"])
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        manager = MNISTDatasetManager()
        train_dataset, test_dataset = manager.load_data()
        clients = config["clients"]
        centralized = experiment.algorithm == "Centralized"
        if centralized:
            partitions = [train_dataset]
        elif config["partition"] == "non_iid":
            partitions = manager.partition_non_iid(len(clients), seed=seed)
        else:
            partitions = manager.partition_iid(len(clients), seed=seed)
        if any(len(partition) == 0 for partition in partitions):
            raise ValueError("Each client must receive at least one MNIST training sample.")
        if not centralized:
            participant_rows = db.query(Participant).filter(Participant.node_id.in_(clients)).all()
            sizes = {client_id: len(partition) for client_id, partition in zip(clients, partitions)}
            for participant in participant_rows:
                participant.dataset_size = sizes[participant.node_id]
                participant.local_epochs = config["local_epochs"]
            db.commit()

        global_model = MNISTCNN()
        global_state = {key: value.detach().cpu().clone() for key, value in global_model.state_dict().items()}
        profile = PROFILE[config["network_profile"]]
        model_bytes = sum(value.numel() * value.element_size() for value in global_state.values())
        model_mb = model_bytes / (1024 * 1024)
        rng = random.Random(seed)
        nodes = {node.id: node for node in db.query(Node).filter(Node.id.in_(clients)).all()} if not centralized else {}
        if not centralized and len(nodes) != len(clients):
            raise ValueError("A configured participant node no longer exists.")

        for round_number in range(1, experiment.rounds + 1):
            round_started = time.perf_counter()
            local_states, sample_counts = [], []
            outcomes = []
            selected_comm_times = []
            selected_latencies = []
            if centralized:
                state, _, _, _, duration = _train_local(
                    global_state, train_dataset, config, seed + round_number * 100_003,
                )
                global_state = state
                local_states.append(state)
                sample_counts.append(len(train_dataset))
            for client_index, (client_id, partition) in enumerate(zip(clients, partitions) if not centralized else []):
                node = nodes[client_id]
                latency_ms = max(0.0, float(node.latency or 0.0) * profile["latency"])
                bandwidth_mbps = max(0.01, float(node.bandwidth or 0.01) * profile["bandwidth"])
                transfer_ms = model_mb * 8 * 1000 / bandwidth_mbps
                communication_ms = 2 * latency_ms + 2 * transfer_ms
                selected_latencies.append(latency_ms)
                selected_comm_times.append(communication_ms)

                if rng.random() < config["dropout_probability"]:
                    outcomes.append(FLClientRound(
                        client_id=client_id, status="DROPPED", samples_used=0,
                        training_duration_s=0, latency_ms=latency_ms,
                        communication_time_ms=communication_ms,
                        data_transferred_mb=0, failure_reason="Simulated client dropout",
                    ))
                    continue
                if communication_ms > config["timeout_ms"]:
                    outcomes.append(FLClientRound(
                        client_id=client_id, status="TIMEOUT", samples_used=0,
                        training_duration_s=0, latency_ms=latency_ms,
                        communication_time_ms=communication_ms,
                        data_transferred_mb=0, failure_reason="Estimated model transfer exceeded the configured timeout",
                    ))
                    continue

                state, samples, accuracy, loss, duration = _train_local(
                    global_state, partition, config,
                    seed + round_number * 100_003 + client_index,
                )
                local_states.append(state)
                sample_counts.append(samples)
                outcomes.append(FLClientRound(
                    client_id=client_id, status="COMPLETED", samples_used=samples,
                    local_accuracy=accuracy, local_loss=loss,
                    training_duration_s=duration, latency_ms=latency_ms,
                    communication_time_ms=communication_ms,
                    data_transferred_mb=2 * model_mb,
                ))

            if not local_states:
                raise RuntimeError(f"Round {round_number} had no clients that completed training.")
            if not centralized:
                global_state = FedAvg.aggregate(local_states, sample_counts)
            global_model.load_state_dict(global_state)
            accuracy, loss = _evaluate(global_model, test_dataset, config["batch_size"])
            elapsed = time.perf_counter() - round_started
            if centralized:
                round_duration_s = elapsed
            else:
                round_duration_s = max((
                    outcome.training_duration_s + outcome.communication_time_ms / 1000
                    for outcome in outcomes if outcome.status == "COMPLETED"
                ), default=0.0)
            fl_round = FLRound(
                experiment_id=experiment.id,
                round=round_number,
                participants_count=len(local_states) if not centralized else 0,
                accuracy=accuracy,
                loss=loss,
                round_duration_s=round_duration_s,
            )
            db.add(fl_round)
            db.flush()
            for outcome in outcomes:
                outcome.round_id = fl_round.id
            db.add_all(outcomes)
            completed = len(local_states) if not centralized else 0
            dropped = len(outcomes) - completed
            db.add(Metric(
                round_id=fl_round.id,
                latency_ms=float(np.mean(selected_latencies)) if selected_latencies else 0.0,
                communication_time_ms=max(selected_comm_times, default=0.0),
                energy_j=max(0.0, round_duration_s * 10.0),
                bandwidth_mbps=float(np.mean([
                    max(0.01, float(nodes[client_id].bandwidth or 0.01) * profile["bandwidth"])
                    for client_id in clients
                ])) if clients else 0.0,
                data_transferred_mb=sum(outcome.data_transferred_mb for outcome in outcomes),
                packet_loss_ratio=dropped / max(len(clients), 1) if clients else 0.0,
            ))
            db.commit()

        experiment.status = "COMPLETED"
        experiment.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        failed = db.query(Experiment).filter(Experiment.id == experiment_id).first()
        if failed:
            failed.status = "FAILED"
            failed.error_message = str(exc)[:500]
            from datetime import datetime, timezone
            failed.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
