"""Shared queue/channel model for training and routing, in one-way milliseconds.

Synthetic fluid M/M/1-inspired queue, not packet-level RF simulation. Future
observations are used for labels/evaluation only, never for route selection.
"""

import math

LINK_TARGET = "next_tick_application_link_delay_ms"


def telemetry(link, layer, tick, payload, load=0.2, reserved=0.0, capacity_scale=1.0):
    capacity = max(0.01, link["bandwidth"] * capacity_scale)
    phase = (int(link.get("id") or 0) * 1.7) % math.tau
    background = max(0.0, min(0.98, load + 0.08 * math.sin(tick / 8 + phase)))
    utilization = min(0.995, background + reserved / capacity)
    free = max(0.0, capacity * (1 - background) - reserved)
    propagation = max(link["distance"] / 299.792458, float(link["latency"]))
    queue = min(1000.0, 2 * utilization / max(0.005, 1 - utilization))
    serialization = payload * 8 / (capacity * 1000)
    delay = propagation + queue + serialization
    return {
        "layer": layer,
        "observed_delay_ms": delay,
        "latency_ms": propagation + queue,
        "bandwidth_mbps": capacity,
        "distance_km": link["distance"],
        "load_ratio": utilization,
        "packet_loss_ratio": max(0.0, utilization - 0.95) * 0.5,
        "jitter_ms": queue * 0.1,
        "payload_bytes": payload,
        "queue_ms": queue,
        "available_mbps": free,
        "tick": tick,
        "link_id": link.get("id"),
        "propagation_processing_ms": propagation,
    }
