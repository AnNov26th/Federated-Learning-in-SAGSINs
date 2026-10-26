"""Feasible fixed-route fluid rate allocation. Units: Mbit, Mbps, seconds."""
import math


def allocate(flows, capacities, policy="minimax"):
    """Return per-flow rates, never exceeding any link's residual capacity.

    minimax minimizes max(overhead + remaining_mbit / rate) over the admitted
    flows, under fixed paths, static capacities and no future arrivals. It uses
    monotone feasibility and bisection, not a global dynamic-network optimum.
    """
    if policy not in {"equal", "demand", "minimax", "deadline"}:
        raise ValueError("Unknown allocation policy")
    if any(not math.isfinite(c) or c < 0 for c in capacities.values()):
        raise ValueError("Capacities must be finite and nonnegative")
    if len({flow["id"] for flow in flows}) != len(flows):
        raise ValueError("Duplicate flow IDs")
    for f in flows:
        if not f["path"] or len(set(f["path"])) != len(f["path"]):
            raise ValueError("Flow must have a nonempty, loop-free link path")
        if any(link not in capacities for link in f["path"]):
            raise ValueError("Missing link capacity")
        if not math.isfinite(f["remaining_mbit"]) or f["remaining_mbit"] <= 0:
            raise ValueError("Remaining volume must be positive")
        if not math.isfinite(f.get("overhead_s", 0)) or f.get("overhead_s", 0) < 0:
            raise ValueError("Overhead must be finite and nonnegative")
    rates = {f["id"]: 0.0 for f in flows}
    feasible = [f for f in flows if all(capacities[e] > 0 for e in f["path"])]
    if not feasible:
        return rates

    if policy == "deadline":
        # Conservative, re-evaluated admission: don't consume scarce capacity on
        # flows that cannot meet their deadline even at the current bottleneck.
        remaining_capacity = dict(capacities)
        admitted=[]
        for f in feasible:
            if not math.isfinite(f.get("time_left_s",float("nan"))) or f["time_left_s"] <= 0:
                raise ValueError("Deadline allocation requires positive remaining time")
        ordered=sorted(feasible,key=lambda f:(f["time_left_s"],f["remaining_mbit"],f["id"]))
        for f in ordered:
            window=f["time_left_s"]-f.get("overhead_s",0)
            if window <= 0:
                continue
            required=f["remaining_mbit"]/window
            if all(remaining_capacity[e]+1e-10 >= required for e in f["path"]):
                rates[f["id"]]=required
                for e in f["path"]:
                    remaining_capacity[e]=max(0,remaining_capacity[e]-required)
                admitted.append(f)
        # Allocate remaining capacity to earliest deadlines, with short jobs as a
        # tie-break. A deferred flow is reconsidered next tick, not destroyed.
        for f in admitted:
            extra=min(min(remaining_capacity[e] for e in f["path"]),
                      max(0,f["remaining_mbit"]-rates[f["id"]]))
            rates[f["id"]]+=extra
            for e in f["path"]:
                remaining_capacity[e]=max(0,remaining_capacity[e]-extra)
        return rates

    if policy in {"equal", "demand"}:
        weights = {f["id"]: f["remaining_mbit"] if policy == "demand" else 1.0 for f in feasible}
        totals = {e: sum(weights[f["id"]] for f in feasible if e in f["path"]) for e in capacities}
        for f in feasible:
            rates[f["id"]] = min(capacities[e] * weights[f["id"]] / totals[e] for e in f["path"])
        return rates

    def candidate(t):
        return {f["id"]: f["remaining_mbit"] / max(1e-12, t - f.get("overhead_s", 0)) for f in feasible}

    def fits(proposal):
        return all(sum(proposal[f["id"]] for f in feasible if e in f["path"]) <= c
                   for e, c in capacities.items())

    low = max(f.get("overhead_s", 0) for f in feasible)
    high = max(1.0, low + 1.0)
    while not fits(candidate(high)):
        high = low + 2 * (high - low)
        if high > 1e15:
            raise ValueError("Numerically infeasible allocation")
    for _ in range(75):
        mid = (low + high) / 2
        if fits(candidate(mid)):
            high = mid
        else:
            low = mid
    rates.update(candidate(high))
    return rates


def assert_capacity(flows, rates, capacities, tolerance=1e-7):
    for edge, capacity in capacities.items():
        used = sum(rates.get(f["id"], 0) for f in flows if edge in f["path"])
        if used > capacity + tolerance:
            raise AssertionError(f"Capacity violated on {edge}: {used} > {capacity}")
