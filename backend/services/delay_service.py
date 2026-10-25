"""Network-delay estimates used by simulated federated-learning runs."""

NETWORK_PROFILES = {
    "normal": {"latency_multiplier": 1.0, "bandwidth_multiplier": 1.0},
    "high_latency": {"latency_multiplier": 10.0, "bandwidth_multiplier": 1.0},
    "low_bandwidth": {"latency_multiplier": 1.0, "bandwidth_multiplier": 0.1},
    "bursty_congestion": {"latency_multiplier": 1.0, "bandwidth_multiplier": 1.0},
    "regime_switching": {"latency_multiplier": 1.0, "bandwidth_multiplier": 1.0},
}


def estimate_communication_ms(latency_ms, bandwidth_mbps, model_size_mb, network_profile="normal"):
    """Estimate a model download and upload over a symmetric client link."""
    try:
        profile = NETWORK_PROFILES[network_profile]
    except KeyError as exc:
        raise ValueError(f"Unknown network profile: {network_profile}") from exc

    latency = max(0.0, float(latency_ms or 0.0)) * profile["latency_multiplier"]
    bandwidth = max(0.01, float(bandwidth_mbps or 0.0)) * profile["bandwidth_multiplier"]
    model_mb = max(0.0, float(model_size_mb or 0.0))
    transfer_ms = model_mb * 8 * 1000 / bandwidth
    return 2 * latency + 2 * transfer_ms
