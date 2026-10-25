"""Federated-learning experiment and paired-comparison APIs."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.models.network import Node
from backend.models.participant import Participant
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLClientRound, FLRound, Metric
from backend.models.network_learning import NetworkDataset, NetworkObservation, NetworkRoundEvaluation, NetworkRoundPrediction
from backend.schemas.base import APIResponse
from backend.schemas.fl import (
    FLClientRoundResult, FLComparisonCreate, FLExperimentCreate, FLExperimentDetail,
    FLExperimentSummary, FLRoundResult,
)
from backend.services.fl_service import run_experiment

router = APIRouter()


def _summary(db, experiment):
    rounds = db.query(FLRound).filter(FLRound.experiment_id == experiment.id).order_by(FLRound.round.desc()).all()
    latest = rounds[0] if rounds else None
    config = experiment.config_json or {}
    network_task = config.get("task") == "network_delay"
    evaluation = db.get(NetworkRoundEvaluation, latest.id) if latest and network_task else None
    actual_duration = None
    if experiment.started_at is not None and experiment.completed_at is not None:
        actual_duration = max(0.0, (experiment.completed_at - experiment.started_at).total_seconds())
    return {
        "id": experiment.id, "scenario_id": experiment.scenario_id,
        "algorithm": experiment.algorithm, "status": experiment.status,
        "target_rounds": experiment.rounds,
        "completed_rounds": sum(
            experiment.algorithm == "Centralized" or row.participants_count > 0
            for row in rounds
        ),
        "latest_accuracy": latest.accuracy if latest and not network_task else None,
        "latest_loss": latest.loss if latest else None,
        "task": config.get("task", "mnist"), "dataset_id": config.get("dataset_id"),
        "latest_mae_ms": evaluation.mae_ms if evaluation else None,
        "latest_rmse_ms": evaluation.rmse_ms if evaluation else None,
        "latest_r2": evaluation.r2 if evaluation else None,
        "is_simulation": experiment.is_simulation,
        "error_message": experiment.error_message,
        "actual_duration_s": actual_duration,
    }


def _scenario(db, scenario_id):
    scenario = (db.query(Scenario).filter(Scenario.id == scenario_id).first()
                if scenario_id is not None else db.query(Scenario).order_by(Scenario.id.asc()).first())
    if scenario is None:
        raise HTTPException(status_code=400, detail="Create or seed a SAGSIN scenario before starting an experiment.")
    return scenario


def _candidate_snapshot(db, scenario, client_count):
    nodes = db.query(Node).filter(Node.scenario_id == scenario.id).all()
    by_id = {node.id: node for node in nodes}
    selected_rows = (
        db.query(Participant).join(Node, Participant.node_id == Node.id)
        .filter(Participant.selected.is_(True), Node.scenario_id == scenario.id)
        .order_by(Participant.id.asc()).all()
    )
    selected_ids = list(dict.fromkeys(row.node_id for row in selected_rows if row.node_id in by_id))
    if selected_ids:
        candidates = [node_id for node_id in selected_ids if by_id[node_id].status == "ACTIVE"]
    else:
        candidates = [node.id for node in nodes if node.status == "ACTIVE"]
    active_count = sum(by_id[node_id].status == "ACTIVE" for node_id in candidates)
    if active_count < client_count:
        raise HTTPException(
            status_code=400,
            detail=f"Only {active_count} ACTIVE candidate nodes are available; {client_count} required.",
        )
    profiles = {
        node_id: {
            "status": by_id[node_id].status,
            "latency": float(by_id[node_id].latency or 0.0),
            "bandwidth": float(by_id[node_id].bandwidth or 0.01),
        }
        for node_id in candidates
    }
    participant_epochs = {
        row.node_id: int(row.local_epochs)
        for row in selected_rows if row.node_id in candidates
    }
    return candidates, profiles, participant_epochs


def _training_snapshot(db, scenario, request, minimum=None):
    from backend.services.regional_pool_service import choose_region
    allowed, profiles, epochs = _candidate_snapshot(db, scenario, 0)
    nodes = db.query(Node).filter(Node.id.in_(allowed)).all()
    selected, region = choose_region(nodes, request.pool_mode, request.region_radius_km, request.region_lat, request.region_lng)
    candidates = [node.id for node in selected]
    required = minimum if minimum is not None else (2 if getattr(request,"algorithm",None)=="Centralized" else request.client_count)
    if len(candidates) < required:
        raise HTTPException(400, detail=f"Pool {request.pool_mode} có {len(candidates)} client hợp lệ, cần {required}. Giảm client/vòng hoặc chọn tâm/bán kính khác; không tự mở rộng khu vực.")
    return candidates, {key:profiles[key] for key in candidates}, {key:value for key,value in epochs.items() if key in candidates}, region


def _config(request, scenario, candidate_pool, profiles, participant_epochs, comparison_id=None, region=None):
    config = request.model_dump(exclude={"scenario_id", "algorithm"}, exclude_unset=False)
    config.update({
        "candidate_pool": candidate_pool,
        "client_profiles": profiles,
        "local_epochs_by_client": participant_epochs,
        "selection_policy": "round_sample",
        "metrics_source": "pytorch_test_set",
        "network_metrics_source": "simulated_from_node_profile",
    })
    if region is not None:
        config["training_region"] = region
    if comparison_id:
        config["comparison_id"] = comparison_id
    return config


def _register_candidate_rows(db, candidate_pool, request):
    existing = {
        row.node_id: row for row in db.query(Participant)
        .filter(Participant.node_id.in_(candidate_pool)).all()
    }
    for node_id in candidate_pool:
        if node_id not in existing:
            db.add(Participant(
                node_id=node_id, dataset_size=0,
                local_epochs=request.local_epochs, selected=False,
            ))


def _network_config(db, request, scenario, comparison_id=None):
    from backend.services.network_dataset_service import create_dataset
    candidates, _, epochs, region = _training_snapshot(db, scenario, request)
    if request.dataset_id is not None:
        dataset = db.get(NetworkDataset, request.dataset_id)
        if dataset is None or dataset.scenario_id != scenario.id:
            raise HTTPException(status_code=400, detail="Dataset must exist and belong to this scenario.")
        if any(getattr(request, key) != dataset.config_json[key] for key in ("partition", "network_profile")) or request.seed != dataset.seed:
            raise HTTPException(status_code=400, detail="Use the dataset's seed, partition and network profile when reusing it.")
    else:
        if request.online_steps < request.rounds:
            raise HTTPException(status_code=400, detail="Online ticks must cover every requested round.")
        try:
            dataset = create_dataset(db, scenario.id, request.seed, request.samples_per_client, request.partition, request.network_profile, request.online_steps,
                                     client_ids=candidates if request.pool_mode=="regional" else None, prediction_target=request.prediction_target)
        except ValueError as error:
            raise HTTPException(400,str(error)) from error
    profiles = dataset.config_json["profiles"]
    if any(client not in profiles for client in candidates):
        raise HTTPException(status_code=400, detail="The candidate pool contains nodes absent from the dataset. Generate a new dataset or select its clients.")
    from sqlalchemy import func
    online_counts = dict(db.query(NetworkObservation.client_id, func.count()).filter(
        NetworkObservation.dataset_id == dataset.id, NetworkObservation.split == "online",
        NetworkObservation.client_id.in_(candidates)).group_by(NetworkObservation.client_id).all())
    if any(online_counts.get(client, 0) < request.rounds for client in candidates):
        raise HTTPException(status_code=400, detail="Dataset has too few online ticks for this pool. Reduce rounds or create a new dataset.")
    _register_candidate_rows(db, candidates, request)
    config = _config(request, scenario, candidates, {client: profiles[client] for client in candidates}, epochs, comparison_id, region)
    config.update({
        "dataset_id": dataset.id, "dataset_fingerprint": dataset.fingerprint,
        "generator_version": dataset.generator_version, "feature_version": dataset.config_json["feature_version"],
        "metrics_source": "held_out_future_network_observations",
        "network_metrics_source": "generated_temporal_network_trace",
        "locality": dataset.config_json["locality"], "target": dataset.config_json["target"],
        "samples_per_client": dataset.config_json["samples_per_client"], "online_steps": dataset.config_json["online_steps"],
    })
    return config


def _create_record(db, scenario, algorithm, request, config):
    experiment = Experiment(
        scenario_id=scenario.id, algorithm=algorithm, rounds=request.rounds,
        learning_rate=request.learning_rate, status="QUEUED", is_simulation=True,
        config_json=config,
    )
    db.add(experiment)
    db.flush()
    return experiment


@router.post("/experiments", response_model=APIResponse[FLExperimentSummary], status_code=202)
def create_experiment(request: FLExperimentCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    scenario = _scenario(db, request.scenario_id)
    if request.task == "network_delay":
        config = _network_config(db, request, scenario)
    elif request.algorithm == "Centralized":
        config = request.model_dump(exclude={"scenario_id", "algorithm"})
        config.update({"metrics_source": "pytorch_test_set", "network_metrics_source": "not_applicable"})
    else:
        candidate_pool, profiles, participant_epochs, region = _training_snapshot(db, scenario, request)
        _register_candidate_rows(db, candidate_pool, request)
        config = _config(request, scenario, candidate_pool, profiles, participant_epochs, region=region)
    experiment = _create_record(db, scenario, request.algorithm, request, config)
    db.commit()
    db.refresh(experiment)
    background_tasks.add_task(run_experiment, experiment.id)
    return APIResponse(data=_summary(db, experiment), message=f"{request.algorithm} experiment queued.")


@router.post("/comparisons", response_model=APIResponse[dict], status_code=202)
def create_comparison(request: FLComparisonCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Queue paired runs differing only in per-round client scheduler."""
    scenario = _scenario(db, request.scenario_id)
    comparison_id = str(uuid.uuid4())
    if request.task == "network_delay":
        shared_config = _network_config(db, request, scenario, comparison_id)
    else:
        candidate_pool, profiles, participant_epochs, region = _training_snapshot(db, scenario, request)
        _register_candidate_rows(db, candidate_pool, request)
        shared_config = _config(request, scenario, candidate_pool, profiles, participant_epochs, comparison_id, region)
    algorithms = ["FedAvg", "DelayAware", "Predictive"] if request.task == "network_delay" else ["FedAvg", "DelayAware"]
    experiments = [_create_record(db, scenario, algorithm, request, dict(shared_config)) for algorithm in algorithms]
    db.commit()
    for experiment in experiments:
        db.refresh(experiment)
        background_tasks.add_task(run_experiment, experiment.id)
    return APIResponse(data={
        "comparison_id": comparison_id,
        "scenario_id": scenario.id,
        "candidate_pool": shared_config["candidate_pool"],
        "shared_config": {k: v for k, v in shared_config.items() if k not in {"client_profiles", "local_epochs_by_client"}},
        "experiments": [_summary(db, experiment) for experiment in experiments],
    }, message="Matched scheduler runs queued with a shared dataset, seed, candidate pool and training configuration.")


@router.get("/experiments", response_model=APIResponse[list[FLExperimentSummary]])
def list_experiments(db: Session = Depends(get_db)):
    experiments = db.query(Experiment).order_by(Experiment.id.desc()).limit(50).all()
    return APIResponse(data=[_summary(db, experiment) for experiment in experiments])


def _detail(db, experiment):
    rounds = db.query(FLRound).filter(FLRound.experiment_id == experiment.id).order_by(FLRound.round.asc()).all()
    round_results = []
    network_task = (experiment.config_json or {}).get("task") == "network_delay"
    for round_row in rounds:
        clients = db.query(FLClientRound).filter(FLClientRound.round_id == round_row.id).order_by(FLClientRound.client_id.asc()).all()
        metric = db.query(Metric).filter(Metric.round_id == round_row.id).first()
        failure_ratio = (sum(client.status != "COMPLETED" for client in clients) / len(clients)) if clients else None
        evaluation = db.get(NetworkRoundEvaluation, round_row.id) if network_task else None
        predictions = db.query(NetworkRoundPrediction).filter(NetworkRoundPrediction.round_id == round_row.id).order_by(NetworkRoundPrediction.client_id).all() if network_task else []
        round_results.append({
            "round": round_row.round, "accuracy": None if network_task else round_row.accuracy, "loss": round_row.loss,
            "participants_count": round_row.participants_count, "selected_count": len(clients),
            "dropped_count": sum(client.status != "COMPLETED" for client in clients),
            "aggregated": experiment.algorithm == "Centralized" or round_row.participants_count > 0,
            "status": "COMPLETED" if experiment.algorithm == "Centralized" or round_row.participants_count > 0 else "FAILED_NO_CLIENTS",
            "round_duration_s": round_row.round_duration_s,
            "metrics": ({
                "latency_ms": metric.latency_ms,
                "communication_time_ms": metric.communication_time_ms,
                "energy_j": metric.energy_j,
                "bandwidth_mbps": metric.bandwidth_mbps,
                "data_transferred_mb": metric.data_transferred_mb,
                "packet_loss_ratio": metric.packet_loss_ratio,
                "client_failure_ratio": failure_ratio,
                "energy_source": "estimated_at_10_watts",
                "round_duration_source": "simulated_parallel_completion_estimate",
            } if metric else None),
            "clients": [FLClientRoundResult.model_validate(client).model_dump() for client in clients],
            "prediction_metrics": ({
                "mae_ms": evaluation.mae_ms, "rmse_ms": evaluation.rmse_ms, "r2": evaluation.r2,
                "validation_mae_ms": evaluation.validation_mae_ms, "persistence_mae_ms": evaluation.persistence_mae_ms,
                "test_samples": evaluation.test_samples, "selection_source": evaluation.selection_source,
                "loss_unit": "log1p_delay_mse",
            } if evaluation else None),
            "predictions": [{
                "client_id": row.client_id, "observation_id": row.observation_id,
                "predicted_delay_ms": row.predicted_delay_ms, "observed_delay_ms": row.observed_delay_ms,
                "rule_delay_ms": row.rule_delay_ms, "selected": row.selected, "model_round": row.model_round,
            } for row in predictions],
        })
    config = dict(experiment.config_json or {})
    config.pop("clients", None)
    return {
        **_summary(db, experiment), "config": config,
        "created_at": experiment.created_at, "rounds": round_results,
    }


@router.get("/experiments/{experiment_id}", response_model=APIResponse[FLExperimentDetail])
def get_experiment(experiment_id: int, db: Session = Depends(get_db)):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return APIResponse(data=_detail(db, experiment))


@router.get("/comparisons/{comparison_id}", response_model=APIResponse[dict])
def get_comparison(comparison_id: str, db: Session = Depends(get_db)):
    experiments = (
        db.query(Experiment)
        .filter(Experiment.config_json["comparison_id"].as_string() == comparison_id)
        .order_by(Experiment.id.asc()).all()
    )
    expected = 3 if experiments and (experiments[0].config_json or {}).get("task") == "network_delay" else 2
    if len(experiments) != expected:
        raise HTTPException(status_code=404, detail="Comparison not found or does not contain all runs.")
    configs = [experiment.config_json or {} for experiment in experiments]
    statuses = [experiment.status for experiment in experiments]
    terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
    comparison_status = (
        "COMPLETED" if all(status == "COMPLETED" for status in statuses) else
        "FAILED" if all(status in terminal_statuses for status in statuses) else
        "RUNNING"
    )
    return APIResponse(data={
        "comparison_id": comparison_id,
        "status": comparison_status,
        "same_candidate_pool": all(config.get("candidate_pool") == configs[0].get("candidate_pool") for config in configs),
        "same_seed": all(config.get("seed") == configs[0].get("seed") for config in configs),
        "same_dataset": all(config.get("dataset_id") == configs[0].get("dataset_id") for config in configs),
        "same_training_config": all(configs[0].get(key) == config.get(key) for config in configs for key in (
            "prediction_target", "pool_mode", "region_radius_km", "region_lat", "region_lng", "training_region",
            "rounds", "client_count", "local_epochs", "learning_rate", "batch_size", "partition",
            "seed", "network_profile", "dropout_probability", "timeout_ms", "task", "dataset_id", "client_profiles", "local_epochs_by_client",
        )),
        "experiments": [_detail(db, experiment) for experiment in experiments],
    })
