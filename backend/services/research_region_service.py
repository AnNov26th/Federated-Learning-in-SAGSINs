"""Explicit access and backbone roles for a reproducible coastal study area."""

from backend.models.network import Node, NetworkLink
from backend.models.scenario import Scenario
from backend.models.research_region import ResearchRegion


def region_for(db, scenario_id):
    return db.get(ResearchRegion, scenario_id)


def create_region(db):
    existing = db.query(Scenario).filter_by(name="SAGSIN Coastal Research v1").first()
    if existing and region_for(db, existing.id):
        return region_for(db, existing.id)
    scenario = Scenario(
        name="SAGSIN Coastal Research v1",
        total_nodes=6,
        ground=3,
        air=1,
        sea=1,
        space=1,
    )
    db.add(scenario)
    db.flush()
    prefix = f"LAB{scenario.id}"
    entries = [
        ("ACCESS", "GROUND", 16.06, 108.22, 0.03, 100, 1),
        ("RELAY", "GROUND", 16.07, 108.32, 0.03, 100, 1),
        ("EDGE", "GROUND", 16.09, 108.52, 0.03, 100, 1),
        ("UAV", "AIR", 16.08, 108.37, 0.5, 30, 2),
        ("SHIP", "SEA", 16.02, 108.32, 0.03, 30, 2),
        ("SAT", "SPACE", 16.06, 108.40, 550, 50, 3),
    ]
    ids = {}
    for name, layer, lat, lng, alt, bandwidth, latency in entries:
        identifier = f"{prefix}-{name}"
        ids[name] = identifier
        db.add(
            Node(
                id=identifier,
                type=layer,
                lat=lat,
                lng=lng,
                alt=alt,
                bandwidth=bandwidth,
                latency=latency,
                status="ACTIVE",
                scenario_id=scenario.id,
                is_simulated=True,
                platform="RESEARCH_STATIC",
                location_name=f"Coastal study / {name}",
                coordinate_source="explicit_research_layout",
            )
        )
    db.flush()
    from backend.services.routing_service import channel_distance, visible

    for a, b, bandwidth, latency in [
        ("ACCESS", "RELAY", 10, 0.25),
        ("RELAY", "EDGE", 10, 0.35),
        ("ACCESS", "UAV", 20, 3),
        ("UAV", "EDGE", 20, 3),
        ("ACCESS", "SHIP", 15, 2),
        ("SHIP", "SAT", 15, 3),
        ("SAT", "EDGE", 15, 3),
    ]:
        first, second = db.get(Node, ids[a]), db.get(Node, ids[b])
        if not visible(first, second):
            raise ValueError(f"Research link lacks line of sight: {a}/{b}")
        db.add(
            NetworkLink(
                source=first.id,
                target=second.id,
                distance=channel_distance(first, second),
                bandwidth=bandwidth,
                latency=latency,
                status="ACTIVE",
            )
        )
    config = {
        "version": "coastal-v1",
        "access_nodes": [ids["ACCESS"]],
        "service_nodes": [ids["EDGE"]],
        "nodes": ids,
        "center": {"lat": 16.06, "lng": 108.22},
        "radius_km": 100,
        "conditions": "normal",
        "disabled_nodes": [],
        "disabled_links": [],
        "background_load": 0.2,
        "note": "Fixed evaluation snapshot, explicit compatible access mast and edge services. Satellite follows no deployment command; no orbital propagation in this experiment.",
    }
    region = ResearchRegion(
        scenario_id=scenario.id, sim_time_s=0, running=False, config_json=config
    )
    db.add(region)
    db.flush()
    return region


def set_conditions(region, name):
    config = dict(region.config_json)
    ids = config["nodes"]
    config.update(
        conditions=name, disabled_nodes=[], disabled_links=[], background_load=0.2
    )
    if name == "congested":
        config["background_load"] = 0.35
    elif name == "terrestrial_failure":
        config["disabled_nodes"] = [ids["RELAY"]]
    elif name == "satellite_fallback":
        config["disabled_nodes"] = [ids["RELAY"], ids["UAV"]]
    elif name == "disconnected":
        config["disabled_nodes"] = [ids["RELAY"], ids["UAV"], ids["SHIP"]]
    elif name != "normal":
        raise ValueError("Unknown study condition")
    region.config_json = config


def link_load(region, link):
    config = region.config_json
    if config["conditions"] == "congested" and config["nodes"]["RELAY"] in (
        link["source"],
        link["target"],
    ):
        return 0.96
    return config["background_load"]
