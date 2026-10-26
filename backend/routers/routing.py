from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from typing import Literal
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from backend.database.database import get_db
from backend.models.scenario import Scenario
from backend.schemas.base import APIResponse
from backend.schemas.routing import EventRouteRequest, EventPlaybackUpdate, SavedEventRequest
from backend.models.routing_event import RoutingEvent
from backend.services.routing_event_service import reservations_for, serialize_event
from backend.services.routing_service import model_candidates, model_summary, route_event, routing_topology

router = APIRouter()


@router.get("/topology", response_model=APIResponse[dict])
def topology_view(scenario_id: int = Query(ge=1), topology: Literal["configured", "estimated", "adaptive"] = "adaptive", db: Session = Depends(get_db)):
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    return APIResponse(data=routing_topology(db, scenario_id, topology))


@router.get("/context", response_model=APIResponse[dict])
def routing_context(db: Session = Depends(get_db)):
    from backend.models.research_region import ResearchRegion
    return APIResponse(data={
        "scenarios": [{"id": s.id, "name": s.name} for s in db.query(Scenario).order_by(Scenario.id)],
        "models": [model_summary(candidate) for candidate in model_candidates(db)],
        "research_regions": [{"scenario_id":row.scenario_id,"center":row.config_json["center"]}
                             for row in db.query(ResearchRegion)],
    })


@router.post("/event", response_model=APIResponse[dict])
def event_route(request: EventRouteRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    _lock_scenario(db, request.scenario_id)
    response = _calculate_event(request, background_tasks, db, reservations_for(db, request.scenario_id))
    db.commit()
    return response


def _calculate_event(request, background_tasks, db, reservations):
    if db.get(Scenario, request.scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    result = route_event(db, request, reservations=reservations)
    if result.get("code")=="ok" and not request.allow_reposition and not result.get("research"):
        result.setdefault("runtime","federated-http-v3")
        result.setdefault("allocation_policy",request.allocation_policy)
    if (result.get("code") != "no_model" or request.policy != "predictive"
            or request.experiment_id or not request.auto_train):
        return APIResponse(data=result)

    from backend.models.network import Node
    from backend.models.simulation import Experiment
    from backend.schemas.fl import FLExperimentCreate
    from backend.services.fl_service import run_experiment
    from backend.routers.federated_learning import _create_record, _network_config, _training_snapshot

    pending = db.query(Experiment).filter(
        Experiment.scenario_id == request.scenario_id,
        Experiment.algorithm == "Predictive",
        Experiment.status.in_(["QUEUED", "RUNNING"]),
    ).order_by(Experiment.id.desc()).all()
    existing = next((row for row in pending if (row.config_json or {}).get("task") == "network_delay"), None)
    if existing:
        experiment = existing
    else:
        active_count = db.query(Node).filter(
            Node.scenario_id == request.scenario_id, Node.status.ilike("ACTIVE"),
        ).count()
        if active_count < 2:
            return APIResponse(data={**result, "code": "training_unavailable",
                                    "reason": "Chưa có model và cần ít nhất 2 node ACTIVE để tự huấn luyện."})
        training_request = FLExperimentCreate(
            scenario_id=request.scenario_id, algorithm="Predictive", task="network_delay",
            rounds=10, client_count=min(5, active_count), samples_per_client=160,
            local_epochs=1, learning_rate=0.01, batch_size=64,
            partition="non_iid", seed=42, network_profile="normal",
            dropout_probability=0.0, timeout_ms=120_000,
            region_lat=request.lat, region_lng=request.lng,
        )
        try:
            # Keep the scenario lock until the caller commits the event too.
            # A savepoint isolates training setup failures without releasing it.
            with db.begin_nested():
                scenario = db.get(Scenario, request.scenario_id)
                candidates, _, _, _ = _training_snapshot(db, scenario, training_request, minimum=2)
                training_request.client_count = min(5, len(candidates))
                config = _network_config(db, training_request, scenario)
                experiment = _create_record(db, scenario, "Predictive", training_request, config)
                db.flush()
            background_tasks.add_task(run_experiment, experiment.id)
        except (HTTPException, ValueError) as error:
            reason = error.detail if isinstance(error, HTTPException) else str(error)
            return APIResponse(data={**result, "code": "training_unavailable",
                                    "reason": f"Chưa có model; không thể tự huấn luyện: {reason}"})
    return APIResponse(data={
        **result, "status": "training", "code": "training",
        "reason": "Đang huấn luyện model Network delay; tuyến sẽ được tính lại khi hoàn tất.",
        "training": {"experiment_id": experiment.id, "status": experiment.status},
    })


def _lock_scenario(db, scenario_id):
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignores FOR UPDATE; acquire its writer lock before reading
        # allocations so concurrent demo requests cannot reserve the same Mbps.
        db.execute(text("UPDATE scenarios SET id = id WHERE id = :id"), {"id": scenario_id})
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).with_for_update().first()
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    return scenario


def _lock_event(db, event_id):
    scenario_id = db.query(RoutingEvent.scenario_id).filter(RoutingEvent.id == event_id).scalar()
    if scenario_id is None:
        raise HTTPException(status_code=404, detail="Điểm đã được xóa hoặc không tồn tại.")
    _lock_scenario(db, scenario_id)
    event = db.query(RoutingEvent).filter(RoutingEvent.id == event_id).populate_existing().with_for_update().first()
    if event is None:
        raise HTTPException(status_code=404, detail="Điểm đã được xóa hoặc không tồn tại.")
    return event


@router.get("/events", response_model=APIResponse[list[dict]])
def saved_events(scenario_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db)):
    query = db.query(RoutingEvent)
    if scenario_id is not None:
        query = query.filter(RoutingEvent.scenario_id == scenario_id)
    return APIResponse(data=[serialize_event(event) for event in query.order_by(RoutingEvent.id)])


@router.post("/events", response_model=APIResponse[dict], status_code=201)
def create_event(request: SavedEventRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    _lock_scenario(db, request.scenario_id)
    existing = db.query(RoutingEvent).filter(RoutingEvent.client_key == request.client_key).with_for_update().first()
    if existing:
        if existing.scenario_id != request.scenario_id:
            raise HTTPException(status_code=409, detail="Mã điểm đã thuộc scenario khác.")
        return APIResponse(data=serialize_event(existing))
    result = _calculate_event(request, background_tasks, db, reservations_for(db, request.scenario_id)).data
    from backend.services.research_region_service import region_for
    from backend.services.research_flow_service import bind_flow
    region=region_for(db,request.scenario_id)
    if region:result=bind_flow(result,request,region.sim_time_s)
    from backend.services.fluid_network_service import bind
    result=bind(db,result,request)
    number = (db.query(func.max(RoutingEvent.display_number)).filter(RoutingEvent.scenario_id == request.scenario_id).scalar() or 0) + 1
    event = RoutingEvent(client_key=request.client_key, display_number=number, scenario_id=request.scenario_id, service=request.service, lat=request.lat, lng=request.lng,
                         config_json=request.model_dump(exclude={"lat", "lng", "service", "client_key"}), result_json=result)
    db.add(event)
    db.commit()
    db.refresh(event)
    return APIResponse(data=serialize_event(event))


@router.delete("/events", response_model=APIResponse[dict])
def delete_all_events(scenario_id: int = Query(ge=1), db: Session = Depends(get_db)):
    _lock_scenario(db, scenario_id)
    events = db.query(RoutingEvent).filter(RoutingEvent.scenario_id == scenario_id).with_for_update().all()
    ids = [event.id for event in events]
    for event in events:
        db.delete(event)
    db.commit()
    return APIResponse(data={"deleted_ids": ids, "deleted_count": len(ids)})


@router.put("/events/{event_id}", response_model=APIResponse[dict])
def recompute_event(event_id: int, request: EventRouteRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    event = _lock_event(db, event_id)
    if event.scenario_id != request.scenario_id:
        raise HTTPException(status_code=409, detail="Không thể chuyển điểm sang scenario khác. Hãy tạo điểm mới.")
    result = _calculate_event(request, background_tasks, db, reservations_for(db, request.scenario_id, event_id)).data
    from backend.services.research_region_service import region_for
    from backend.services.research_flow_service import bind_flow
    region=region_for(db,request.scenario_id)
    if region:result=bind_flow(result,request,region.sim_time_s,(event.result_json or {}).get("flow"))
    from backend.services.fluid_network_service import bind
    result=bind(db,result,request,(event.result_json or {}).get("flow"))
    event.service, event.lat, event.lng = request.service, request.lat, request.lng
    event.config_json = request.model_dump(exclude={"lat", "lng", "service"})
    event.result_json, event.playback_json = result, None
    db.commit()
    db.refresh(event)
    return APIResponse(data=serialize_event(event))


@router.patch("/events/{event_id}/playback", response_model=APIResponse[dict])
def update_playback(event_id: int, request: EventPlaybackUpdate, db: Session = Depends(get_db)):
    event = _lock_event(db, event_id)
    result = event.result_json or {}
    mobility = result.get("mobility") or {}
    if not mobility.get("moves") or request.snapshot_at != result.get("snapshot_at"):
        raise HTTPException(status_code=409, detail="Lượt điều động đã thay đổi. Tải lại điểm trước khi cập nhật.")
    elapsed = min(mobility["eta_s"], max(request.elapsed_s, (event.playback_json or {}).get("elapsed_s", 0)))
    event.playback_json = {"elapsed_s": elapsed, "paused": request.paused}
    db.commit()
    return APIResponse(data=event.playback_json)


@router.delete("/events/{event_id}", response_model=APIResponse[dict])
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = _lock_event(db, event_id)
    db.delete(event)
    db.commit()
    return APIResponse(data={"id": event_id, "deleted": True})
