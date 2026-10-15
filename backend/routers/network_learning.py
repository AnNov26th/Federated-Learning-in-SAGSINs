"""Data provenance, client raw partitions, and saved-model inference APIs."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.models.network_learning import NetworkDataset, NetworkObservation, NetworkRoundEvaluation
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment, FLRound
from backend.schemas.base import APIResponse
from backend.services.network_dataset_service import create_dataset, dataset_summary

router = APIRouter()


class DatasetCreate(BaseModel):
    scenario_id: int = Field(ge=1)
    seed: int = Field(default=42, ge=0, le=2147483647)
    samples_per_client: int = Field(default=160, ge=40, le=2000)
    partition: Literal["iid", "non_iid"] = "non_iid"
    network_profile: Literal["normal", "high_latency", "low_bandwidth"] = "normal"


@router.post("/datasets", response_model=APIResponse[dict], status_code=201)
def seed_network_dataset(request: DatasetCreate, db: Session = Depends(get_db)):
    if db.get(Scenario, request.scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    try:
        dataset = create_dataset(db, **request.model_dump())
        db.commit()
        return APIResponse(data=dataset_summary(db, dataset), message="Generated immutable network dataset with per-client temporal splits.")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/datasets", response_model=APIResponse[list[dict]])
def list_datasets(scenario_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    query = db.query(NetworkDataset)
    if scenario_id is not None:
        query = query.filter(NetworkDataset.scenario_id == scenario_id)
    return APIResponse(data=[dataset_summary(db, row) for row in query.order_by(NetworkDataset.id.desc()).limit(30)])


@router.get("/datasets/{dataset_id}", response_model=APIResponse[dict])
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    dataset = db.get(NetworkDataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return APIResponse(data={**dataset_summary(db, dataset), "config": dataset.config_json})


@router.get("/datasets/{dataset_id}/observations", response_model=APIResponse[dict])
def get_observations(dataset_id: int, client_id: str | None = None,
                     split: Literal["train", "validation", "online", "test"] | None = None,
                     limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    if db.get(NetworkDataset, dataset_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    query = db.query(NetworkObservation).filter(NetworkObservation.dataset_id == dataset_id)
    if client_id:
        query = query.filter(NetworkObservation.client_id == client_id)
    if split:
        query = query.filter(NetworkObservation.split == split)
    count = query.count()
    rows = query.order_by(NetworkObservation.client_id, NetworkObservation.sequence).offset(offset).limit(limit).all()
    return APIResponse(data={"total": count, "offset": offset, "rows": [{
        "id": row.id, "client_id": row.client_id, "sequence": row.sequence, "split": row.split,
        "features": row.features_json, "target_delay_ms": row.target_delay_ms,
    } for row in rows]})


class PredictionInput(BaseModel):
    layer: Literal["SPACE", "AIR", "GROUND", "SEA"]
    observed_delay_ms: float = Field(ge=0, le=10000000, allow_inf_nan=False)
    latency_ms: float = Field(ge=0, le=10000000, allow_inf_nan=False)
    bandwidth_mbps: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    distance_km: float = Field(ge=0, le=1000000, allow_inf_nan=False)
    load_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    packet_loss_ratio: float = Field(ge=0, lt=1, allow_inf_nan=False)
    jitter_ms: float = Field(ge=0, le=10000000, allow_inf_nan=False)
    payload_bytes: int = Field(gt=0, le=1000000000)


@router.post("/experiments/{experiment_id}/predict", response_model=APIResponse[dict])
def saved_model_predict(experiment_id: int, request: PredictionInput, db: Session = Depends(get_db)):
    experiment = db.get(Experiment, experiment_id)
    if experiment is None or (experiment.config_json or {}).get("task") != "network_delay":
        raise HTTPException(status_code=404, detail="Network prediction experiment not found.")
    result = db.query(FLRound, NetworkRoundEvaluation).join(
        NetworkRoundEvaluation, NetworkRoundEvaluation.round_id == FLRound.id,
    ).filter(FLRound.experiment_id == experiment_id).order_by(FLRound.round.desc()).first()
    if not result:
        raise HTTPException(status_code=409, detail="No trained checkpoint is available yet.")
    from backend.algorithms.network_delay_model import load_checkpoint, predict
    round_row, evaluation = result
    dataset = db.get(NetworkDataset, experiment.config_json["dataset_id"])
    if request.payload_bytes != dataset.config_json["payload_bytes"]:
        raise HTTPException(status_code=400, detail="Use the payload size of this model's training dataset.")
    from backend.services.fl_service import _training_lock
    with _training_lock:
        prediction = predict(load_checkpoint(evaluation.checkpoint_json), [request.model_dump()])[0]
    return APIResponse(data={"experiment_id": experiment_id, "model_round": round_row.round,
                             "target": "next_tick_model_round_trip_ms", "predicted_delay_ms": prediction})
