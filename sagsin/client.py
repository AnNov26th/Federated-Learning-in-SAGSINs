"""Independent authenticated HTTP worker. Raw rows have no network endpoint."""
import hashlib
import json
import secrets
import time
import threading
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .config import ExperimentConfig
from .dataset import generate, load_local, save_local
from .model import DelayModel, envelope, errors, predictions, train, validate_envelope
from .topology import BY_NODE, stable_seed, configure


class TrainingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    round: int = Field(ge=1, le=100)
    model: dict


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: dict
    split: str = Field(pattern="^(validation|test)$")
    local_epochs: int = Field(0, ge=0, le=2000)


def create_client(client_id, config, directory, token, database_settings, dataset_override=None, execution_lock=None):
    import torch
    torch.set_num_threads(1)
    directory = Path(directory)
    run_id = directory.parent.parent.name
    if dataset_override is None:
        fingerprint = save_local(database_settings, run_id, generate(client_id, config), config.model_dump())
        rows = {split: load_local(database_settings, run_id, split) for split in ("train", "validation", "test")}
    else:
        rows = dataset_override
        fingerprint = "in-memory-test-fixture"
    if any(not part for part in rows.values()):
        raise ValueError("Client has an empty split")
    # Hash is evidence of the data used, not a raw-row transmission.
    cache = {}
    last_round = 0
    training_lock = execution_lock or threading.Lock()
    app = FastAPI(title=f"SAGSIN local client {client_id}", docs_url=None, redoc_url=None)

    def authenticate(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "Invalid client credential")

    @app.get("/health", dependencies=[Depends(authenticate)])
    def health():
        return {"client_id": client_id, "layer": BY_NODE[client_id].layer,
                "splits": {key: len(value) for key, value in rows.items()},
                "dataset_sha256": fingerprint}

    def local_train_impl(request: TrainingRequest):
        nonlocal last_round
        digest = hashlib.sha256(json.dumps(request.model, sort_keys=True).encode()).hexdigest()
        if request.round in cache:
            if cache[request.round][0] != digest:
                raise HTTPException(409, "Conflicting duplicate round")
            return cache[request.round][1]
        if request.round <= last_round:
            raise HTTPException(409, "Stale round")
        try:
            model = validate_envelope(request.model)
            if model.family != config.model_family:
                raise ValueError("Model family differs from the experiment")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        started = time.perf_counter()
        train(model, rows["train"], config.local_epochs, config.learning_rate,
              config.batch_size, stable_seed(config.seed, client_id, request.round), config.optimizer, config.loss)
        result = {"client_id": client_id, "round": request.round, "samples": len(rows["train"]),
                  "model": envelope(model,config.transport_codec), "training_s": time.perf_counter() - started}
        cache[request.round] = (digest, result)
        last_round = request.round
        return result

    @app.post("/train", dependencies=[Depends(authenticate)])
    def local_train(request: TrainingRequest):
        with training_lock:
            return local_train_impl(request)

    def evaluate_impl(request: EvaluationRequest):
        try:
            model = validate_envelope(request.model)
            if model.family != config.model_family:
                raise ValueError("Model family differs from the experiment")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        part = rows[request.split]
        result = {"client_id": client_id, "layer": BY_NODE[client_id].layer,
                  "fl": errors(predictions(model, part), part),
                  "persistence": errors([r["observed_delay_ms"] for r in part], part),
                  "linear_trend": errors([max(0,r["observed_delay_ms"]+r["delta_delay_ms"]) for r in part], part),
                  "moving_average": errors([(r["observed_delay_ms"] + r["previous_delay_ms"]) / 2 for r in part], part)}
        if request.split == "test":
            torch.manual_seed(config.seed)
            local = DelayModel(config.model_family)
            if request.local_epochs:
                train(local, rows["train"], request.local_epochs, config.learning_rate,
                      config.batch_size, stable_seed(config.seed, client_id, "local-only"), config.optimizer, config.loss)
            result["local_only"] = errors(predictions(local, part), part)
            result["local_epochs"] = request.local_epochs
        return result

    @app.post("/evaluate", dependencies=[Depends(authenticate)])
    def evaluate(request: EvaluationRequest):
        with training_lock:
            return evaluate_impl(request)

    return app


def serve_client(client_id, config_value, directory, token, listener, database_settings):
    import uvicorn
    config = ExperimentConfig(**config_value)
    configure(config.topology)
    app = create_client(client_id, config, directory, token, database_settings)
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(sockets=[listener])


def serve_shard(identifiers, config_value, directory, token, listener, settings):
    """Bounded process hosting authenticated, separate logical client apps.

    Each app retains its own data, DB account, lock and round cache. The
    coordinator receives only models/aggregate metrics, independent of pool size.
    """
    import uvicorn
    config = ExperimentConfig(**config_value)
    configure(config.topology)
    app = FastAPI(docs_url=None, redoc_url=None)
    execution_lock=threading.Lock()
    for identifier in identifiers:
        key = hashlib.sha256(identifier.encode()).hexdigest()[:24]
        local_config = config.model_copy(update={"local_epochs":config.local_epochs_by_client.get(identifier,config.local_epochs)})
        app.mount("/" + key, create_client(identifier, local_config, Path(directory)/key, token, settings[identifier],execution_lock=execution_lock))
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(sockets=[listener])


def serve_shard_logged(identifiers, config_value, directory, token, listener, settings):
    try:
        serve_shard(identifiers,config_value,directory,token,listener,settings)
    except BaseException:
        import traceback
        folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256(identifiers[0].encode()).hexdigest()[:24]
        (folder/(key+"-startup.log")).write_text(traceback.format_exc(),encoding="utf-8")
        raise
