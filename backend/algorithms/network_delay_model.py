"""Small FedAvg-compatible regressor, with fixed, public feature scaling.

Only measurements at t are features. The target is communication delay at t+1.
The residual starts at zero, giving an interpretable persistence cold start.
"""
import math

import torch
from torch import nn

FEATURE_VERSION = "network-features-v1"
LAYERS = ("GROUND", "AIR", "SPACE", "SEA")


def encode_features(row):
    return [
        math.log1p(row["observed_delay_ms"]) / 10,
        math.log1p(row["latency_ms"]) / 10,
        math.log1p(row["bandwidth_mbps"]) / 10,
        math.log1p(row["distance_km"]) / 10,
        row["load_ratio"], row["packet_loss_ratio"],
        math.log1p(row["jitter_ms"]) / 10,
        math.log1p(row["payload_bytes"]) / 20,
        *[float(row["layer"] == layer) for layer in LAYERS],
    ]


class NetworkDelayRegressor(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(12, 32), nn.Tanh(), nn.Linear(32, 16), nn.Tanh(), nn.Linear(16, 1))
        nn.init.zeros_(self.layers[-1].weight)
        nn.init.zeros_(self.layers[-1].bias)

    def forward(self, inputs):
        return inputs[:, 0] * 10 + self.layers(inputs).squeeze(-1)


def payload_bytes():
    # Architecture size, independent of random parameter initialization.
    return (12 * 32 + 32 + 32 * 16 + 16 + 16 + 1) * 4


def checkpoint(model):
    return {key: value.detach().cpu().tolist() for key, value in model.state_dict().items()}


def load_checkpoint(values):
    model = NetworkDelayRegressor()
    model.load_state_dict({key: torch.tensor(value, dtype=torch.float32) for key, value in values.items()})
    return model


def predict(model, features):
    model.eval()
    with torch.no_grad():
        inputs = torch.tensor([encode_features(row) for row in features], dtype=torch.float32)
        return torch.expm1(model(inputs).clamp(0, math.log1p(10_000_000))).tolist()
