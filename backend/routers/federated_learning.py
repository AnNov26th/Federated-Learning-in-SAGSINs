import random

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.models.network import Node
from backend.models.participant import Participant
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLClientRound, FLRound, Metric
from backend.schemas.base import APIResponse
from backend.schemas.fl import FLExperimentCreate, FLExperimentDetail, FLExperimentSummary, FLRoundResult
from backend.services.fl_service import run_experiment

router = APIRouter()


def _summary(db, experiment):
    rounds = db.query(FLRound).filter(FLRound.experiment_id == experiment.id).order_by(FLRound.round.desc()).all()
    latest = rounds[0] if rounds else None
    return {
        "id": experiment.id,
        "scenario_id": experiment.scenario_id,
        "algorithm": experiment.algorithm,
        "status": experiment.status,
        "target_rounds": experiment.rounds,
        "completed_rounds": len(rounds),
        "latest_accuracy": latest.accuracy if latest else None,
        "latest_loss": latest.loss if latest else None,
        "is_simulation": experiment.is_simulation,
        "error_message": experiment.error_message,
    }


@router.post("/experiments", response_model=APIResponse[FLExperimentSummary], status_code=202)
def create_experiment(
    request: FLExperimentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    scenario = (
        db.query(Scenario).filter(Scenario.id == request.scenario_id).first()
        if request.scenario_id is not None else db.query(Scenario).order_by(Scenario.id.asc()).first()
    )
    if scenario is None:
        raise HTTPException(status_code=400, detail="Create or seed a SAGSIN scenario before starting an experiment.")

    client_ids = []
    if request.algorithm == "FedAvg":
        scenario_nodes = db.query(Node).filter(Node.scenario_id == scenario.id)
        active_nodes = scenario_nodes.filter(Node.status == "ACTIVE").all()
        if not active_nodes:
            active_nodes = scenario_nodes.all()
        by_id = {node.id: node for node in active_nodes}
        selected_rows = (
            db.query(Participant)
            .filter(Participant.selected.is_(True))
            .order_by(Participant.id.asc())
            .all()
        )
        selected_ids = list(dict.fromkeys(row.node_id for row in selected_rows if row.node_id in by_id))
        rng = random.Random(request.seed)
        if selected_ids:
            if len(selected_ids) < request.client_count:
                raise HTTPException(
                    status_code=400,
                    detail=f"Only {len(selected_ids)} active participants are selected; select at least {request.client_count}.",
                )
            rng.shuffle(selected_ids)
            client_ids = selected_ids[:request.client_count]
        else:
            if len(active_nodes) < request.client_count:
                raise HTTPException(status_code=400, detail=f"Only {len(active_nodes)} active nodes are available.")
            client_ids = [node.id for node in rng.sample(active_nodes, request.client_count)]
            existing = {row.node_id: row for row in db.query(Participant).filter(Participant.node_id.in_(client_ids)).all()}
            for node_id in client_ids:
                if node_id in existing:
                    existing[node_id].selected = True
                    existing[node_id].local_epochs = request.local_epochs
                else:
                    db.add(Participant(
                        node_id=node_id,
                        dataset_size=0,
                        local_epochs=request.local_epochs,
                        selected=True,
                    ))
            db.flush()

    config = request.model_dump(exclude={"scenario_id", "algorithm"})
    config["clients"] = client_ids
    config["metrics_source"] = "pytorch_test_set"
    config["network_metrics_source"] = "simulated_from_node_profile" if request.algorithm == "FedAvg" else "not_applicable"
    experiment = Experiment(
        scenario_id=scenario.id,
        algorithm=request.algorithm,
        rounds=request.rounds,
        learning_rate=request.learning_rate,
        status="QUEUED",
        is_simulation=True,
        config_json=config,
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    background_tasks.add_task(run_experiment, experiment.id)
    return APIResponse(data=_summary(db, experiment), message=f"{request.algorithm} experiment queued.")


@router.get("/experiments", response_model=APIResponse[list[FLExperimentSummary]])
def list_experiments(db: Session = Depends(get_db)):
    experiments = db.query(Experiment).order_by(Experiment.id.desc()).limit(50).all()
    return APIResponse(data=[_summary(db, experiment) for experiment in experiments])


@router.get("/experiments/{experiment_id}", response_model=APIResponse[FLExperimentDetail])
def get_experiment(experiment_id: int, db: Session = Depends(get_db)):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    rounds = db.query(FLRound).filter(FLRound.experiment_id == experiment.id).order_by(FLRound.round.asc()).all()
    round_results = []
    for round_row in rounds:
        clients = db.query(FLClientRound).filter(FLClientRound.round_id == round_row.id).order_by(FLClientRound.client_id.asc()).all()
        metric = db.query(Metric).filter(Metric.round_id == round_row.id).first()
        round_results.append({
            "round": round_row.round,
            "accuracy": round_row.accuracy,
            "loss": round_row.loss,
            "participants_count": round_row.participants_count,
            "selected_count": len(clients),
            "dropped_count": sum(client.status != "COMPLETED" for client in clients),
            "round_duration_s": round_row.round_duration_s,
            "metrics": ({
                "latency_ms": metric.latency_ms,
                "communication_time_ms": metric.communication_time_ms,
                "energy_j": metric.energy_j,
                "bandwidth_mbps": metric.bandwidth_mbps,
                "data_transferred_mb": metric.data_transferred_mb,
                "packet_loss_ratio": metric.packet_loss_ratio,
            } if metric else None),
            "clients": clients,
        })
    config = dict(experiment.config_json or {})
    config.pop("clients", None)
    return APIResponse(data={
        **_summary(db, experiment),
        "config": config,
        "created_at": experiment.created_at,
        "rounds": round_results,
    })
