"""Finite fluid flows on a shared clock, evaluated on an unseen future window.

    Traffic and background traces are paired across policies. Policies see t;
    realized capacities at t+1 cap actual service, preventing future leakage.
    This is not a packet/RF emulator; latency is a fluid completion estimate.
"""
import copy
import math
import random
from .allocation import allocate, assert_capacity
from .routing import edge_costs, shortest_path
from .topology import LINKS, BY_LINK, channel, stable_seed


def workload(config):
    rng = random.Random(stable_seed(config.seed, "workload"))
    destination = (config.topology or {}).get("destination", "EDGE")
    sources = [n["id"] for n in config.topology["nodes"] if n["id"] != destination] if config.topology else ["G1", "G2", "SEA1", "SEA2", "S1", "A1"]
    start = config.samples_per_client + 20
    return [{"id": f"F{i:03}", "source": rng.choice(sources), "destination": destination,
             "arrival": start + rng.randrange(max(2, config.network_ticks // 3)),
             "size_mbit": rng.uniform(8, 48), "deadline_s": config.network_ticks * 0.7}
            for i in range(config.flow_count)]


def simulate(config, model, route_policy, allocation_policy, on_tick=None):
    specs = workload(config)
    flows = [dict(spec, remaining_mbit=spec["size_mbit"], state="pending", path=[],
                  route_nodes=[], route_changes=0, delivered_mbit=0.0, overhead_s=0.0,
                  wire_mbit=0.0, started=None, finished=None) for spec in specs]
    first = config.samples_per_client + 20
    audit = []
    for tick in range(first, first + config.network_ticks):
        if on_tick:
            on_tick()
        current = {e.id: channel(e, tick, config.seed, config.profile) for e in LINKS}
        capacities = {e: c["available_mbps"] for e, c in current.items()}
        costs = edge_costs(tick, config, route_policy, model)
        active = []
        for f in flows:
            if f["state"] in {"completed", "expired"} or tick < f["arrival"]:
                continue
            if tick - f["arrival"] >= f["deadline_s"]:
                f["state"] = "expired"
                f["path"] = []
                continue
            broken=not f["path"] or any(not current[e]["active"] for e in f["path"])
            should_review=route_policy!="static" and tick-f.get("last_route_tick",-1000)>=config.reroute_interval
            if broken or should_review:
                route = shortest_path(f["source"], f["destination"], costs)
                if route is None:
                    f["state"] = "waiting"
                    f["path"] = []
                    continue
                old_cost=sum(costs[e] for e in f["path"]) if not broken else float("inf")
                accept=broken or route["cost_ms"] < old_cost*(1-config.reroute_improvement)
                f["last_route_tick"]=tick
                if accept:
                    if f["route_nodes"] and f["route_nodes"] != route["nodes"]:
                        f["route_changes"] += 1
                        f["pause_s"]=.05
                    f["path"], f["route_nodes"] = route["links"], route["nodes"]
                    audit.append({"tick": tick, "flow": f["id"], "kind": "route",
                              "policy": route_policy, "nodes": route["nodes"],
                              "links": route["links"], "predicted_reference_ms": route["cost_ms"],
                              "information_time": tick,"reason":"broken_or_initial" if broken else "predicted_improvement",
                              "handover_pause_s":f.get("pause_s",0)})
            # Reference serialization must not be counted again in completion overhead.
            f["overhead_s"] = sum(max(0, costs[e] - config.payload_bytes * 8 /
                                      (max(.01, capacities[e]) * 1000)) for e in f["path"]) / 1000
            f["state"] = "transmitting"
            f["time_left_s"] = f["deadline_s"]-(tick-f["arrival"])
            active.append(f)
        rates = allocate(active, capacities, allocation_policy)
        assert_capacity(active, rates, capacities)
        realized = {e.id: channel(e, tick + 1, config.seed, config.profile) for e in LINKS}
        # All allocations share each edge; scale by the bottleneck if capacity drops.
        edge_total = {e: sum(rates[f["id"]] for f in active if e in f["path"]) for e in capacities}
        effective = {}
        for f in active:
            factor = min(min(1, realized[e]["available_mbps"] / max(1e-12, edge_total[e])) for e in f["path"])
            effective[f["id"]] = rates[f["id"]] * factor
        assert_capacity(active, effective, {e: c["available_mbps"] for e, c in realized.items()})
        for f in active:
            rate = effective[f["id"]]
            pause=f.pop("pause_s",0)
            amount = min(f["remaining_mbit"], rate*max(0,1-pause))
            if amount > 0 and f["started"] is None:
                f["started"] = tick
            f["remaining_mbit"] -= amount
            f["delivered_mbit"] += amount
            f["wire_mbit"] += amount * len(f["path"])
            if f["remaining_mbit"] <= 1e-8:
                overhead = sum(BY_LINK[e].propagation_ms + realized[e]["queue_ms"] for e in f["path"]) / 1000
                f["finished"] = tick + pause + amount / max(rate, 1e-12) + overhead
                f["state"] = "completed" if f["finished"] - f["arrival"] <= f["deadline_s"] else "expired"
            audit.append({"tick": tick, "flow": f["id"], "kind": "allocation",
                          "links": list(f["path"]), "rate_mbps": rates[f["id"]],
                          "decision":"deferred" if rates[f["id"]]<=0 else "allocated",
                          "realized_mbps": rate, "served_mbit": amount,
                          "remaining_mbit": max(0, f["remaining_mbit"]),
                          "capacity_mbps": {e: capacities[e] for e in f["path"]}})
    for f in flows:
        if f["state"] not in {"completed", "expired"}:
            f["state"] = "expired"
    durations = sorted(f["finished"] - f["arrival"] for f in flows if f["state"] == "completed")
    throughputs = [f["delivered_mbit"] / max(1, (f["finished"] or first + config.network_ticks) - f["arrival"]) for f in flows]
    fairness = sum(throughputs)**2 / (len(flows) * sum(v*v for v in throughputs)) if any(throughputs) else 0
    summary = {"route_policy": route_policy, "allocation_policy": allocation_policy,
               "flows": len(flows), "completed": len(durations),
               "delivery_ratio": len(durations) / len(flows),
               "mean_completion_s": sum(durations) / len(durations) if durations else None,
               "p95_completion_s": durations[min(len(durations)-1, math.ceil(.95*len(durations))-1)] if durations else None,
               "throughput_mbps": sum(f["delivered_mbit"] for f in flows) / config.network_ticks,
               "wire_mbit": sum(f["wire_mbit"] for f in flows),
               "fairness_jain": fairness, "reroutes": sum(f["route_changes"] for f in flows),
               "capacity_violations": 0, "evaluation_start_tick": first}
    summary["deferred_flow_ticks"]=sum(a.get("decision")=="deferred" for a in audit)
    return {"summary": summary, "flows": flows, "audit": audit}


def compare_network(config, model, on_tick=None):
    # Ablation separates route prediction from rate allocation improvements.
    policies = [("static", "equal"), ("current", "equal"), ("fl", "equal"),
                ("current", "demand"), ("current", "minimax"), ("fl", "minimax"),
                ("current","deadline"),("fl","deadline")]
    return [simulate(config, model, route, allocation, on_tick) for route, allocation in policies]
