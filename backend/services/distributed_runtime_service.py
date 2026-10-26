"""B's federated engine behind A's original experiment/data/API contracts."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session
from backend.models.network import Node, NetworkLink
from backend.models.network_learning import NetworkDataset, NetworkRoundEvaluation
from backend.models.simulation import Experiment, FLRound, FLClientRound, Metric
from backend.services.training_progress_service import publish
from sagsin.config import ExperimentConfig, FEATURE_VERSION, TARGET, SIMULATOR_VERSION
from sagsin.paths import OUTPUT
from sagsin.storage import read_json

RUNTIME = "federated-http-v3"
CONTROLS = {}
CONTROL_LOCK = threading.Lock()


def topology_snapshot(db, scenario_id):
    from backend.services.topology_service import feasible_pair
    from backend.services.routing_service import channel_distance
    nodes = {n.id:n for n in db.query(Node).filter_by(scenario_id=scenario_id,status="ACTIVE").all()}
    edges = []
    for e in db.query(NetworkLink).filter_by(status="ACTIVE").all():
        a,b = nodes.get(e.source),nodes.get(e.target)
        if not a or not b or not feasible_pair(a,b,allow_ground_backbone=True):
            continue
        distance = channel_distance(a,b)
        edges.append(dict(id=f"A{e.id}",source=a.id,target=b.id,
            capacity_mbps=min(a.bandwidth,b.bandwidth,e.bandwidth),
            propagation_ms=max(e.latency,distance/299.792458),distance_km=distance))
    degrees = Counter(key for e in edges for key in (e["source"],e["target"]))
    ground = [n for n in nodes.values() if n.type=="GROUND"]
    if not ground or not edges:
        raise HTTPException(400,"Scenario cần GROUND đích và link ACTIVE khả thi; không tự sinh đường nối.")
    from backend.services.research_region_service import region_for
    region = region_for(db,scenario_id)
    preferred = set(region.config_json["service_nodes"]) if region else set()
    target = sorted(ground,key=lambda n:(n.id not in preferred,-degrees[n.id],n.id))[0].id
    return dict(nodes=[dict(id=n.id,layer=n.type,x=n.lng,y=n.lat) for n in nodes.values()],
                links=edges,destination=target,source="active_feasible_scenario_snapshot",scenario_id=scenario_id)


def create_config(db, request, scenario, candidates, epochs, region, comparison_id=None):
    snapshot = topology_snapshot(db,scenario.id)
    if request.network_profile in {"high_latency","low_bandwidth"}:
        for edge in snapshot["links"]:
            if request.network_profile=="high_latency":edge["propagation_ms"]*=10
            else:edge["capacity_mbps"]*=.1
    linked = {key for e in snapshot["links"] for key in (e["source"],e["target"])}
    missing = set(candidates)-linked
    if missing:
        raise HTTPException(400,f"{len(missing)} client không có link khả thi để thu telemetry; kiểm tra topology: {sorted(missing)[:5]}")
    profiles = {n.id:dict(layer=n.type,latency=n.latency,bandwidth=n.bandwidth,status=n.status)
                for n in db.query(Node).filter(Node.id.in_(candidates))}
    profile = {"normal":"normal","high_latency":"mixed","low_bandwidth":"congested",
               "bursty_congestion":"mixed","regime_switching":"mixed"}[request.network_profile]
    runtime = ExperimentConfig(seed=request.seed,model_family=request.model_family,
        transport_codec=request.transport_codec,client_count=len(candidates),client_ids=candidates,
        clients_per_round=request.client_count,max_workers=request.max_workers,topology=snapshot,
        rounds=request.rounds,samples_per_client=request.samples_per_client,local_epochs=request.local_epochs,
        local_epochs_by_client=epochs,learning_rate=request.learning_rate,batch_size=request.batch_size,
        partition=request.partition,profile=profile,selection={"DelayAware":"delay_aware","Predictive":"predictive"}.get(getattr(request,"algorithm",""),"random"),
        dropout_probability=request.dropout_probability,timeout_s=request.timeout_ms/1000)
    if request.dataset_id:
        dataset = db.get(NetworkDataset,request.dataset_id)
        if not dataset or dataset.scenario_id!=scenario.id or dataset.config_json.get("runtime")!=RUNTIME:
            raise HTTPException(400,"Dataset không thuộc runtime phân tán của scenario này.")
        saved = dataset.config_json
        if any(saved[k]!=getattr(request,k) for k in ("seed","partition","samples_per_client","network_profile")):
            raise HTTPException(400,"Dùng đúng seed, partition, profile và số mẫu của dataset đã lưu.")
        if any(c not in saved["profiles"] for c in candidates):
            raise HTTPException(400,"Pool chứa client ngoài dataset đã lưu.")
        runtime = runtime.model_copy(update={"topology":saved["topology"]})
    else:
        metadata = dict(runtime=RUNTIME,target=TARGET,feature_version=FEATURE_VERSION,profiles=profiles,
            partition=request.partition,seed=request.seed,network_profile=request.network_profile,
            samples_per_client=request.samples_per_client,online_steps=0,payload_bytes=runtime.payload_bytes,
            locality="client_mysql_accounts_http_updates_only",topology=snapshot,counts={},client_counts={})
        digest = hashlib.sha256(json.dumps(metadata,sort_keys=True).encode()).hexdigest()
        dataset=NetworkDataset(scenario_id=scenario.id,seed=request.seed,generator_version=SIMULATOR_VERSION,
                               fingerprint=digest,config_json=metadata)
        db.add(dataset);db.flush()
    config=request.model_dump(exclude={"scenario_id","algorithm"})
    config.update(runtime=RUNTIME,dataset_id=dataset.id,candidate_pool=candidates,client_profiles=profiles,
        local_epochs_by_client=epochs,training_region=region,feature_version=FEATURE_VERSION,target=TARGET,
        dataset_fingerprint=dataset.fingerprint,distributed_config=runtime.model_dump(),
        runtime_id=uuid.uuid4().hex,metrics_source="client_aggregate_metrics",network_metrics_source="paired_fluid_simulator",
        locality="client_mysql_accounts_http_updates_only")
    if comparison_id:config["comparison_id"]=comparison_id
    return config


def directory(config):
    key=config["runtime_id"]
    if len(key)!=32 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("Invalid runtime identifier")
    return OUTPUT/"experiments"/key


def cancel(identifier):
    with CONTROL_LOCK:
        CONTROLS.setdefault(identifier,threading.Event()).set()


def recover(db):
    for row in db.query(Experiment).filter(Experiment.status.in_(["RUNNING","QUEUED"])):
        if (row.config_json or {}).get("runtime")==RUNTIME:
            row.status="INTERRUPTED"
            row.error_message="Backend dừng trước khi hoàn tất; có thể tiếp tục checkpoint vòng gần nhất."
    db.commit()


def run(db, experiment):
    from sagsin.database import credentials, provision
    from sagsin.experiment import run_experiment
    config=dict(experiment.config_json)
    runtime=ExperimentConfig(**config["distributed_config"])
    folder=directory(config)
    with CONTROL_LOCK:event=CONTROLS.setdefault(experiment.id,threading.Event())
    def check():
        if event.is_set():raise InterruptedError("Đã hủy theo yêu cầu")
    check()
    try:known=credentials()["clients"]
    except RuntimeError:known={}
    if any(c not in known for c in runtime.client_ids):
        provision(runtime.client_ids)
    check()
    previous_bytes=sum(v.data_transferred_mb*1024*1024 for v in db.query(Metric).join(FLRound,Metric.round_id==FLRound.id).filter(FLRound.experiment_id==experiment.id))
    def progress(value):
        nonlocal previous_bytes
        check()
        phase=value.get("stage","training")
        if phase=="clients_ready":
            dataset=db.get(NetworkDataset,config["dataset_id"])
            meta=dict(dataset.config_json)
            meta["client_counts"]={c:h["splits"] for c,h in value["clients"].items()}
            meta["counts"]={s:sum(h["splits"][s] for h in value["clients"].values()) for s in ("train","validation","test")}
            meta["client_fingerprints"]={c:h["dataset_sha256"] for c,h in value["clients"].items()}
            dataset.config_json=meta;db.commit()
        if "rounds" in value:
            checkpoint=read_json(folder/"checkpoint.json")
            for record in value["rounds"]:
                if db.query(FLRound.id).filter_by(experiment_id=experiment.id,round=record["round"]).first():continue
                quality=record["validation"]
                row=FLRound(experiment_id=experiment.id,round=record["round"],participants_count=sum(c["status"]=="completed" for c in record["clients"]),
                    accuracy=0,loss=quality["mae_ms"],round_duration_s=record["wall_s"])
                db.add(row);db.flush()
                for c in record["clients"]:
                    db.add(FLClientRound(round_id=row.id,client_id=c["client"],status=c["status"].upper(),samples_used=c.get("samples",0),
                        training_duration_s=c.get("training_s",0),communication_time_ms=c.get("http_s",0)*1000,
                        latency_ms=0,data_transferred_mb=0,failure_reason=c.get("error")))
                cumulative=sum(v["sent_bytes"]+v["received_bytes"] for v in value.get("communication",{}).values())
                db.add(Metric(round_id=row.id,latency_ms=0,communication_time_ms=record["wall_s"]*1000,
                    energy_j=0,bandwidth_mbps=0,data_transferred_mb=max(0,cumulative-previous_bytes)/(1024*1024),packet_loss_ratio=0))
                previous_bytes=cumulative
                db.add(NetworkRoundEvaluation(round_id=row.id,mae_ms=quality["mae_ms"],rmse_ms=quality["rmse_ms"],r2=None,
                    validation_mae_ms=quality["mae_ms"],persistence_mae_ms=record["persistence"]["mae_ms"],test_samples=0,
                    selection_source="validation_only_http",checkpoint_json=read_json(folder/"audit"/f"round-{record['round']:03}.json")["global_after"]))
                db.commit()
        phase={"clients":"preparing","clients_ready":"preparing","training":"round_completed","evaluation":"evaluating","network":"evaluating"}.get(phase,phase)
        extra={}
        if value.get("rounds"):
            extra["clients"]={c["client"]:dict(status=c["status"].upper(),samples_used=c.get("samples",0),
                training_duration_s=c.get("training_s",0),communication_time_ms=c.get("http_s",0)*1000) for c in value["rounds"][-1]["clients"]}
        publish(db,experiment,phase,value.get("round"),selected=value.get("selected"),message=value.get("message",""),**extra)
    result=run_experiment(runtime,folder,progress,check,resume=bool(config.get("resume_requested")))
    check()
    last=db.query(FLRound).filter_by(experiment_id=experiment.id).order_by(FLRound.round.desc()).first()
    evaluation=db.get(NetworkRoundEvaluation,last.id)
    quality=result["test"]["fl"]
    evaluation.mae_ms=quality["mae_ms"];evaluation.rmse_ms=quality["rmse_ms"]
    evaluation.test_samples=quality["count"];evaluation.persistence_mae_ms=result["test"]["persistence"]["mae_ms"]
    evaluation.selection_source="held_out_test_http"
    updated=dict(experiment.config_json)
    updated.update(distributed_result=dict(test=result["test"],network=result["network"],communication=result["communication"],versions=result["versions"]),resume_requested=False)
    experiment.config_json=updated
    db.commit()


def predict_features(checkpoint,features):
    """Explicit cold start if routing has no compatible previous observation."""
    from sagsin.model import predictions,validate_envelope
    converted=[]
    for f in features:
        current=f["observed_delay_ms"]
        converted.append(dict(layer=f["layer"],observed_delay_ms=current,previous_delay_ms=f.get("previous_delay_ms",current),
            delta_delay_ms=f.get("delta_delay_ms",0),load_before=f.get("load_before",f.get("load",f.get("load_ratio",0))),
            propagation_ms=f.get("propagation_ms",f.get("latency_ms",0)),distance_km=f["distance_km"],
            available_mbps=f.get("available_mbps",f.get("bandwidth_mbps",1)),load=f.get("load",f.get("load_ratio",0)),
            delta_load=f.get("delta_load",0),queue_ms=f.get("queue_ms",0),payload_bytes=f["payload_bytes"]))
    return predictions(validate_envelope(checkpoint),converted)


def application_features(link,layer,tick,payload,config,load=.35,reserved=0,stored=None):
    """Same history/queue generator as client training, with live reservations."""
    from sagsin.topology import Link,channel
    from sagsin.dataset import feature_row
    edge=Link(f"A{link['id']}",link["source"],link["target"],link["bandwidth"],
        max(link["latency"],link["distance"]/299.792458),link["distance"])
    if stored:edge=Link(**stored)
    row=feature_row(edge,layer,int(tick),config["seed"],config["profile"],payload)
    nominal=edge.capacity_mbps
    for field in ("load","load_before"):row[field]=min(.98,max(.01,row[field]+load-.35))
    current=max(.001,nominal*(1-row["load"])-reserved)
    before=max(.001,nominal*(1-row["load_before"])-reserved)
    row.update(available_mbps=current,queue_ms=3*row["load"]/(1-row["load"]))
    row["observed_delay_ms"]=edge.propagation_ms+row["queue_ms"]+payload*8/(current*1000)
    row["previous_delay_ms"]=edge.propagation_ms+3*row["load_before"]/(1-row["load_before"])+payload*8/(before*1000)
    row["delta_delay_ms"]=row["observed_delay_ms"]-row["previous_delay_ms"]
    row["delta_load"]=row["load"]-row["load_before"]
    row.update(latency_ms=edge.propagation_ms,bandwidth_mbps=current,load_ratio=row["load"],packet_loss_ratio=0,jitter_ms=0)
    if not channel(edge,int(tick),config["seed"],config["profile"])["active"]:
        row.update(available_mbps=0,bandwidth_mbps=0)
    return row
