
import math
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List
from backend.database.database import get_db
from backend.models.network import Node, NetworkLink
from backend.schemas.network import (
    NetworkLinkCreate,
    NetworkLinkUpdate,
    Node as NodeSchema,
    NodeCreate,
    NodeUpdate,
)
from backend.schemas.base import APIResponse

router = APIRouter()

@router.get("/nodes", response_model=APIResponse[List[NodeSchema]])
def get_nodes(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()
    return APIResponse(data=nodes)

@router.get("/links", response_model=APIResponse[List[dict]])
def get_links(db: Session = Depends(get_db)):
    links = db.query(NetworkLink).order_by(NetworkLink.id.asc()).all()
    return APIResponse(data=[{
        "id": link.id,
        "source": link.source,
        "target": link.target,
        "distance": link.distance,
        "bandwidth": link.bandwidth,
        "latency": link.latency,
        "status": link.status,
        "last_heartbeat": link.last_heartbeat,
    } for link in links])

@router.post("/links", response_model=APIResponse[dict])
def create_link(link: NetworkLinkCreate, db: Session = Depends(get_db)):
    if link.source == link.target:
        raise HTTPException(status_code=400, detail="A network link must connect two different nodes.")
    endpoints = db.query(Node).filter(Node.id.in_([link.source, link.target])).all()
    by_id = {node.id: node for node in endpoints}
    if link.source not in by_id or link.target not in by_id:
        raise HTTPException(status_code=404, detail="Both link endpoints must exist.")
    duplicate = db.query(NetworkLink).filter(
        or_(
            (NetworkLink.source == link.source) & (NetworkLink.target == link.target),
            (NetworkLink.source == link.target) & (NetworkLink.target == link.source),
        )
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="A link between these nodes already exists.")

    source = by_id[link.source]
    target = by_id[link.target]
    lat1, lat2 = math.radians(source.lat), math.radians(target.lat)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(target.lng - source.lng)
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    central_angle = 2 * math.asin(min(1.0, math.sqrt(haversine)))
    radius_source = 6371.0 + source.alt
    radius_target = 6371.0 + target.alt
    distance = math.sqrt(max(0.0, radius_source**2 + radius_target**2 - 2 * radius_source * radius_target * math.cos(central_angle)))

    db_link = NetworkLink(
        source=link.source,
        target=link.target,
        distance=distance,
        bandwidth=link.bandwidth,
        latency=link.latency,
        status=link.status,
    )
    db.add(db_link)
    try:
        db.commit()
        db.refresh(db_link)
        return APIResponse(data={
            "id": db_link.id,
            "source": db_link.source,
            "target": db_link.target,
            "distance": db_link.distance,
            "bandwidth": db_link.bandwidth,
            "latency": db_link.latency,
            "status": db_link.status,
            "last_heartbeat": db_link.last_heartbeat,
        })
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Could not save network link.") from exc

@router.patch("/links/{link_id}", response_model=APIResponse[dict])
def update_link(link_id: int, changes: NetworkLinkUpdate, db: Session = Depends(get_db)):
    link = db.query(NetworkLink).filter(NetworkLink.id == link_id).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Network link not found.")
    link.status = changes.status
    db.commit()
    db.refresh(link)
    return APIResponse(data={
        "id": link.id,
        "source": link.source,
        "target": link.target,
        "distance": link.distance,
        "bandwidth": link.bandwidth,
        "latency": link.latency,
        "status": link.status,
        "last_heartbeat": link.last_heartbeat,
    })

@router.delete("/links/{link_id}", response_model=APIResponse[dict])
def delete_link(link_id: int, db: Session = Depends(get_db)):
    link = db.query(NetworkLink).filter(NetworkLink.id == link_id).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Network link not found.")
    db.delete(link)
    db.commit()
    return APIResponse(data={"id": link_id, "deleted": True})

@router.post("/nodes", response_model=APIResponse[NodeSchema])
def create_node(node: NodeCreate, db: Session = Depends(get_db)):
    db_node = Node(**node.model_dump())
    db.add(db_node)
    try:
        db.commit()
        db.refresh(db_node)
        return APIResponse(data=db_node)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/nodes/{node_id}", response_model=APIResponse[NodeSchema])
def update_node(node_id: str, changes: NodeUpdate, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found.")
    updates = changes.model_dump(exclude_unset=True)
    if not updates or any(value is None for value in updates.values()):
        raise HTTPException(status_code=422, detail="Provide at least one valid non-null node field.")
    for field, value in updates.items():
        setattr(node, field, value)
    db.commit()
    db.refresh(node)
    return APIResponse(data=node)
