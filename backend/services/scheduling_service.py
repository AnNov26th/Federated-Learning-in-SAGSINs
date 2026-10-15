"""Deterministic client-selection policies for FL experiments."""

import random

from backend.services.delay_service import estimate_communication_ms


def select_clients(
    algorithm,
    candidate_ids,
    client_profiles,
    client_count,
    seed,
    round_number,
    model_size_mb,
    network_profile="normal",
    predicted_delays=None,
):
    """Select ACTIVE clients with either uniform FedAvg or delay-aware policy."""
    active_ids = sorted({
        client_id for client_id in candidate_ids
        if client_id in client_profiles
        and str(client_profiles[client_id].get("status", "")).upper() == "ACTIVE"
    })
    if len(active_ids) < client_count:
        raise ValueError(f"Only {len(active_ids)} ACTIVE candidate nodes are available; {client_count} required.")

    if algorithm == "FedAvg":
        rng = random.Random(int(seed) + int(round_number) * 100_003)
        return rng.sample(active_ids, client_count)

    if algorithm == "Predictive":
        import math
        if predicted_delays is None or any(
            client not in predicted_delays or not math.isfinite(predicted_delays[client]) or predicted_delays[client] < 0
            for client in active_ids
        ):
            raise ValueError("Predictive scheduling requires finite, nonnegative predictions for every ACTIVE client.")
        return sorted(active_ids, key=lambda client: (predicted_delays[client], client))[:client_count]

    if algorithm == "DelayAware":
        ranked = sorted(active_ids, key=lambda client_id: (
            estimate_communication_ms(
                client_profiles[client_id].get("latency"),
                client_profiles[client_id].get("bandwidth"),
                model_size_mb,
                network_profile,
            ),
            client_id,
        ))
        return ranked[:client_count]

    raise ValueError(f"Unsupported FL selection algorithm: {algorithm}")
