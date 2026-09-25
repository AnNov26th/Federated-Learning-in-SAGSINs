from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.models.network import NetworkLink, Node
from backend.models.participant import Participant
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLRound, Metric
from backend.schemas.base import APIResponse

router = APIRouter()


@router.get("/stats", response_model=APIResponse)
def get_dashboard_stats(
    scenario_id: Optional[int] = Query(default=None, ge=1),
    algorithm: Optional[str] = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
):
    try:
        node_rows = db.query(Node.type, func.count(Node.id)).group_by(Node.type).all()
        node_counts = {str(node_type).upper(): count for node_type, count in node_rows}
        topology = {
            "total": sum(node_counts.values()),
            "space": node_counts.get("SPACE", 0),
            "air": node_counts.get("AIR", 0),
            "ground": node_counts.get("GROUND", 0),
            "sea": node_counts.get("SEA", 0),
            "links": db.query(NetworkLink).count(),
            "active_links": db.query(NetworkLink).filter(func.upper(NetworkLink.status) == "ACTIVE").count(),
            "average_link_latency": db.query(func.avg(NetworkLink.latency)).scalar(),
        }

        participant_stats = db.query(
            func.count(Participant.id),
            func.coalesce(func.sum(case((Participant.selected.is_(True), 1), else_=0)), 0),
        ).one()
        participants = {"total": participant_stats[0], "selected": int(participant_stats[1] or 0)}

        experiment_query = db.query(Experiment, Scenario.name).outerjoin(
            Scenario, Scenario.id == Experiment.scenario_id
        )
        if scenario_id is not None:
            experiment_query = experiment_query.filter(Experiment.scenario_id == scenario_id)
        if algorithm:
            experiment_query = experiment_query.filter(Experiment.algorithm == algorithm)
        experiment_rows = experiment_query.order_by(Experiment.id.desc()).limit(10).all()
        recent_experiments = []
        latest_experiment = experiment_rows[0][0] if experiment_rows else None

        scenarios = db.query(Scenario.id, Scenario.name).order_by(Scenario.name.asc()).all()
        algorithms = [row[0] for row in db.query(Experiment.algorithm).distinct().order_by(Experiment.algorithm.asc()).all()]

        for experiment, scenario_name in experiment_rows:
            progress = db.query(
                func.count(FLRound.id),
                func.max(FLRound.round),
            ).filter(FLRound.experiment_id == experiment.id).one()
            completed_rounds, current_round = progress
            final_accuracy = (
                db.query(FLRound.accuracy)
                .filter(FLRound.experiment_id == experiment.id)
                .order_by(FLRound.round.desc())
                .limit(1)
                .scalar()
            )
            if completed_rounds >= experiment.rounds:
                status = "completed"
            elif completed_rounds:
                status = "in_progress"
            else:
                status = "not_started"
            recent_experiments.append({
                "id": experiment.id,
                "scenario": scenario_name or "Unknown scenario",
                "algorithm": experiment.algorithm,
                "target_rounds": experiment.rounds,
                "completed_rounds": completed_rounds,
                "current_round": current_round or 0,
                "accuracy": final_accuracy,
                "status": status,
            })

        fl_rounds = []
        if latest_experiment:
            rows = (
                db.query(
                    FLRound.round,
                    FLRound.accuracy,
                    FLRound.loss,
                    FLRound.participants_count,
                    func.avg(Metric.latency),
                    func.avg(Metric.energy_consumption),
                )
                .outerjoin(Metric, Metric.round_id == FLRound.id)
                .filter(FLRound.experiment_id == latest_experiment.id)
                .group_by(
                    FLRound.id,
                    FLRound.round,
                    FLRound.accuracy,
                    FLRound.loss,
                    FLRound.participants_count,
                )
                .order_by(FLRound.round.asc())
                .all()
            )
            for round_number, accuracy, loss, participant_count, latency, energy in rows:
                fl_rounds.append({
                    "round": round_number,
                    "accuracy": accuracy,
                    "loss": loss,
                    "participants": participant_count,
                    "latency": latency,
                    "energy": energy,
                })

        inactive_links = topology["links"] - topology["active_links"]
        alerts = []
        if inactive_links > 0:
            alerts.append({
                "severity": "warning",
                "title": "Inactive network links",
                "message": f"{inactive_links} of {topology['links']} links are not marked ACTIVE.",
            })
        if topology["total"] == 0:
            alerts.append({
                "severity": "info",
                "title": "No topology data",
                "message": "Add network nodes to populate the topology overview.",
            })

        latest = recent_experiments[0] if recent_experiments else None
        data = {
            "topology": topology,
            "participants": participants,
            "latest_experiment": latest,
            "recent_experiments": recent_experiments,
            "fl_training": fl_rounds,
            "alerts": alerts,
            "filters": {
                "scenarios": [{"id": scenario[0], "name": scenario[1]} for scenario in scenarios],
                "algorithms": algorithms,
                "selected_scenario_id": scenario_id,
                "selected_algorithm": algorithm,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return APIResponse(data=data)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Dashboard data is temporarily unavailable.") from exc
