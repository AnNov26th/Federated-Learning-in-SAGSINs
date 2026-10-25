"""Read-only sizing preview, durable progress snapshot and reconnectable SSE."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.database.database import get_db
from backend.models.network import Node
from backend.models.network_learning import NetworkDataset, NetworkObservation
from backend.models.simulation import Experiment, FLRound
from backend.routers.federated_learning import _scenario, _training_snapshot
from backend.schemas.fl import FLExperimentCreate
from backend.schemas.base import APIResponse
from backend.algorithms.network_delay_model import payload_bytes

router = APIRouter()
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def snapshot(db, experiment):
    config = experiment.config_json or {}
    progress = dict(config.get("training_progress", {"revision": 0, "phase": experiment.status.lower(), "clients": {}}))
    if experiment.status in TERMINAL:
        progress["phase"] = experiment.status.lower()
    completed = db.query(func.count(FLRound.id)).filter(FLRound.experiment_id == experiment.id,
        True if experiment.algorithm == "Centralized" else FLRound.participants_count > 0).scalar()
    return {"id": experiment.id, "scenario_id": experiment.scenario_id, "algorithm": experiment.algorithm,
            "status": experiment.status, "target_rounds": experiment.rounds, "completed_rounds": completed,
            "task": config.get("task", "mnist"), "error_message": experiment.error_message,
            "progress": progress}


@router.get("/training-context")
def context(scenario_id: int, pool_mode: str = "regional", region_radius_km: float = 1500,
            region_lat: float | None = None, region_lng: float | None = None, db: Session = Depends(get_db)):
    from pydantic import ValidationError
    try:
        settings = FLExperimentCreate(scenario_id=scenario_id, pool_mode=pool_mode, region_radius_km=region_radius_km,
                                      region_lat=region_lat, region_lng=region_lng)
    except ValidationError as error:
        raise HTTPException(422, str(error))
    scenario = _scenario(db, scenario_id)
    candidates, _, epochs, region = _training_snapshot(db, scenario, settings, minimum=0)
    types = dict(db.query(Node.id, Node.type).filter(Node.id.in_(candidates)).all())
    from backend.services.research_region_service import region_for
    return APIResponse(data={"scenario_id": scenario.id, "candidate_pool": candidates,
        "candidate_count": len(candidates), "local_epochs_by_client": epochs, "training_region": region,
        "client_types": types, "default_target": "application_link" if region_for(db,scenario.id) else "fl_rtt"})


@router.post("/preview")
def preview(request: FLExperimentCreate, db: Session = Depends(get_db)):
    scenario = _scenario(db, request.scenario_id)
    if request.task == "mnist" and request.algorithm == "Centralized":
        return APIResponse(data={"task": "mnist", "candidate_count": 0,
            "note": "Đối chứng MNIST tập trung dùng toàn bộ tập train chuẩn; không chia dữ liệu theo node hoặc khu vực."})
    candidates, _, epochs, region = _training_snapshot(db, scenario, request)
    if request.task != "network_delay":
        return APIResponse(data={"task": request.task, "candidate_count": len(candidates),
            "note": "MNIST: số mẫu local được xác định từ phân vùng khi nạp dataset; không tải dữ liệu trong dự toán."})
    per_client = {}
    if request.dataset_id is not None:
        dataset = db.get(NetworkDataset, request.dataset_id)
        if dataset is None or dataset.scenario_id != scenario.id:
            raise HTTPException(400, "Dataset must belong to this scenario.")
        config = dataset.config_json
        if any(getattr(request, key) != config[key] for key in ("partition", "network_profile")) or request.seed != dataset.seed:
            raise HTTPException(400, "Use the dataset's seed, partition and network profile.")
        if any(client not in config["profiles"] for client in candidates):
            raise HTTPException(400, "Some pool clients are absent from this dataset. Choose another pool or create a new dataset.")
        counts = db.query(NetworkObservation.client_id, NetworkObservation.split, func.count()).filter(
            NetworkObservation.dataset_id == dataset.id).group_by(NetworkObservation.client_id, NetworkObservation.split).all()
        for client, split, count in counts:
            per_client.setdefault(client, {})[split] = count
    else:
        if request.online_steps < request.rounds:
            raise HTTPException(400, "Online ticks must be at least the number of rounds.")
        n = request.samples_per_client
        counts = {"train": int(n*.6), "validation": int(n*.2), "test": n-int(n*.6)-int(n*.2), "online": request.online_steps}
        ids = [row[0] for row in db.query(Node.id).filter_by(scenario_id=scenario.id, status="ACTIVE")]
        per_client = {client: dict(counts) for client in (candidates if request.pool_mode == "regional" else ids)}
    splits = ("train", "validation", "online", "test")
    for client in candidates:
        per_client.setdefault(client, {})
    limits = {split: {"min": min(per_client[client].get(split, 0) for client in candidates),
                      "max": max(per_client[client].get(split, 0) for client in candidates)} for split in splits}
    if any(limits[split]["min"] < 1 for split in splits):
        raise HTTPException(400, "Every pool client needs train, validation, online and test samples.")
    if limits["online"]["min"] < request.rounds:
        raise HTTPException(400, f"Dataset supports only {limits['online']['min']} online rounds for this pool. Reduce rounds or generate new data.")
    pool_counts = {split: sum(per_client[client].get(split, 0) for client in candidates) for split in splits}
    dataset_counts = {split: sum(row.get(split, 0) for row in per_client.values()) for split in splits}
    selected = len(candidates) if request.algorithm == "Centralized" else request.client_count
    return APIResponse(data={"task": request.task, "source": "saved_dataset" if request.dataset_id else "estimate",
        "training_region": region, "candidate_count": len(candidates), "dataset_client_count": len(per_client), "dataset_counts": dataset_counts,
        "dataset_total": sum(dataset_counts.values()), "pool_counts": pool_counts, "per_client": limits,
        "first_round_samples": {"min": pool_counts["train"] if request.algorithm == "Centralized" else selected*limits["train"]["min"],
                                "max": pool_counts["train"] if request.algorithm == "Centralized" else selected*limits["train"]["max"]},
        "epoch_overrides": len(epochs), "features": 12, "outputs": 1, "parameters": 961, "payload_bytes": payload_bytes()})


@router.get("/activity")
def activity(scenario_id: int, db: Session = Depends(get_db)):
    query = db.query(Experiment).filter_by(scenario_id=scenario_id)
    active = query.filter(Experiment.status.notin_(TERMINAL)).order_by(Experiment.id.desc()).limit(20).all()
    chosen = active or query.order_by(Experiment.id.desc()).limit(1).all()
    return APIResponse(data=[snapshot(db, row) for row in chosen])


@router.get("/experiments/{experiment_id}/progress")
def progress(experiment_id: int, db: Session = Depends(get_db)):
    row = db.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(404, "Experiment not found.")
    return APIResponse(data=snapshot(db, row))


def read_snapshot(bind, experiment_id):
    with Session(bind) as db:
        row = db.get(Experiment, experiment_id)
        return snapshot(db, row) if row else None


@router.get("/experiments/{experiment_id}/events")
def events(experiment_id: int, request: Request, db: Session = Depends(get_db)):
    if db.get(Experiment, experiment_id) is None:
        raise HTTPException(404, "Experiment not found.")
    bind = db.get_bind()
    db.rollback()  # Release the read connection before keeping an SSE response open.

    async def stream():
        previous = None
        heartbeat = 0
        while not await request.is_disconnected():
            current = await run_in_threadpool(read_snapshot, bind, experiment_id)
            if current is None:
                return
            marker = (current["progress"]["revision"], current["status"], current["completed_rounds"])
            if marker != previous:
                previous = marker
                yield f"id: {marker[0]}\nevent: progress\ndata: {json.dumps(current)}\n\n"
            if current["status"] in TERMINAL:
                return
            heartbeat += 1
            if heartbeat % 20 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
