"""Federated-learning experiment and paired-comparison APIs."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.models.network import Node
from backend.models.participant import Participant
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLClientRound, FLRound, Metric
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
        "latest_accuracy": latest.accuracy if latest else None,
        "latest_loss": latest.loss if latest else None,
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


def _config(request, scenario, candidate_pool, profiles, participant_epochs, comparison_id=None):
    config = request.model_dump(exclude={"scenario_id", "algorithm"}, exclude_unset=False)
    config.update({
        "candidate_pool": candidate_pool,
        "client_profiles": profiles,
        "local_epochs_by_client": participant_epochs,
        "selection_policy": "round_sample",
        "metrics_source": "pytorch_test_set",
        "network_metrics_source": "simulated_from_node_profile",
    })
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
    if request.algorithm == "Centralized":
        config = request.model_dump(exclude={"scenario_id", "algorithm"})
        config.update({"metrics_source": "pytorch_test_set", "network_metrics_source": "not_applicable"})
    else:
        candidate_pool, profiles, participant_epochs = _candidate_snapshot(db, scenario, request.client_count)
        _register_candidate_rows(db, candidate_pool, request)
        config = _config(request, scenario, candidate_pool, profiles, participant_epochs)
    experiment = _create_record(db, scenario, request.algorithm, request, config)
    db.commit()
    db.refresh(experiment)
    background_tasks.add_task(run_experiment, experiment.id)
    return APIResponse(data=_summary(db, experiment), message=f"{request.algorithm} experiment queued.")


@router.post("/comparisons", response_model=APIResponse[dict], status_code=202)
def create_comparison(request: FLComparisonCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Queue paired runs differing only in per-round client scheduler."""
    scenario = _scenario(db, request.scenario_id)
    candidate_pool, profiles, participant_epochs = _candidate_snapshot(db, scenario, request.client_count)
    _register_candidate_rows(db, candidate_pool, request)
    comparison_id = str(uuid.uuid4())
    shared_config = _config(request, scenario, candidate_pool, profiles, participant_epochs, comparison_id)
    fedavg = _create_record(db, scenario, "FedAvg", request, dict(shared_config))
    delay_aware = _create_record(db, scenario, "DelayAware", request, dict(shared_config))
    db.commit()
    db.refresh(fedavg)
    db.refresh(delay_aware)
    background_tasks.add_task(run_experiment, fedavg.id)
    background_tasks.add_task(run_experiment, delay_aware.id)
    return APIResponse(data={
        "comparison_id": comparison_id,
        "scenario_id": scenario.id,
        "candidate_pool": candidate_pool,
        "shared_config": {k: v for k, v in shared_config.items() if k not in {"client_profiles", "local_epochs_by_client"}},
        "experiments": [_summary(db, fedavg), _summary(db, delay_aware)],
    }, message="FedAvg and Delay-Aware runs queued with the same scenario, candidate pool, seed, and training configuration.")


@router.get("/experiments", response_model=APIResponse[list[FLExperimentSummary]])
def list_experiments(db: Session = Depends(get_db)):
    experiments = db.query(Experiment).order_by(Experiment.id.desc()).limit(50).all()
    return APIResponse(data=[_summary(db, experiment) for experiment in experiments])


def _detail(db, experiment):
    rounds = db.query(FLRound).filter(FLRound.experiment_id == experiment.id).order_by(FLRound.round.asc()).all()
    round_results = []
    for round_row in rounds:
        clients = db.query(FLClientRound).filter(FLClientRound.round_id == round_row.id).order_by(FLClientRound.client_id.asc()).all()
        metric = db.query(Metric).filter(Metric.round_id == round_row.id).first()
        failure_ratio = (sum(client.status != "COMPLETED" for client in clients) / len(clients)) if clients else None
        round_results.append({
            "round": round_row.round, "accuracy": round_row.accuracy, "loss": round_row.loss,
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
                "client_failure_ratio": failure_ratio,
                "energy_source": "estimated_at_10_watts",
                "round_duration_source": "simulated_parallel_completion_estimate",
            } if metric else None),
            "clients": [FLClientRoundResult.model_validate(client).model_dump() for client in clients],
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
    if len(experiments) != 2:
        raise HTTPException(status_code=404, detail="Comparison not found or does not contain both runs.")
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
        "same_candidate_pool": configs[0].get("candidate_pool") == configs[1].get("candidate_pool"),
        "same_seed": configs[0].get("seed") == configs[1].get("seed"),
        "same_training_config": all(configs[0].get(key) == configs[1].get(key) for key in (
            "rounds", "client_count", "local_epochs", "learning_rate", "batch_size", "partition",
            "seed", "network_profile", "dropout_probability", "timeout_ms",
        )),
        "experiments": [_detail(db, experiment) for experiment in experiments],
    })
