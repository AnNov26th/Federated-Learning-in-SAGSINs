"""Adapted from the original project's residual MLP, with versioned history features."""
import math
import base64
import struct
import zlib
import torch
from torch import nn
from .config import FEATURE_VERSION, TARGET

LAYERS = ("GROUND", "AIR", "SPACE", "SEA")
INPUT_SIZE = 15


def encode(row):
    return [math.log1p(row["observed_delay_ms"]) / 10,
            math.log1p(row["propagation_ms"]) / 10,
            math.log1p(row["available_mbps"]) / 5,
            math.log1p(row["distance_km"]) / 10,
            row["load"], math.log1p(row["queue_ms"]) / 10,
            math.log1p(row["payload_bytes"]) / 20,
            max(-2, min(2, row["delta_delay_ms"] / 20)),
            math.log1p(row["previous_delay_ms"]) / 10,
            row["delta_load"], row["load_before"],
            *[float(row["layer"] == layer) for layer in LAYERS]]


class DelayModel(nn.Module):
    def __init__(self, family="residual_mlp"):
        super().__init__()
        if family not in {"residual_mlp", "trend"}:
            raise ValueError("Unknown model family")
        self.family = family
        if family == "residual_mlp":
            self.layers = nn.Sequential(nn.Linear(INPUT_SIZE, 32), nn.Tanh(),
                                        nn.Linear(32, 16), nn.Tanh(), nn.Linear(16, 1))
            nn.init.zeros_(self.layers[-1].weight)
            nn.init.zeros_(self.layers[-1].bias)
        else:
            # Learned damped log-trend. No tick, link identity or future schedule.
            self.trend = nn.Linear(4, 1, bias=False)
            nn.init.zeros_(self.trend.weight)

    def forward(self, x):
        if self.family == "residual_mlp":
            correction = self.layers(x).squeeze(-1)
        else:
            delta = ((x[:, 0] - x[:, 8]) * 10).clamp(-0.2, 0.2)
            basis = torch.stack((delta, delta * x[:, 4], x[:, 9].clamp(-.15, .15),
                                 delta * x[:, 10]), dim=1)
            correction = self.trend(basis).squeeze(-1).clamp(-.3, .3)
        return x[:, 0] * 10 + correction


def state_json(model):
    return {key: value.detach().cpu().tolist() for key, value in model.state_dict().items()}


def load_state(values, family="residual_mlp", codec="json"):
    model = DelayModel(family)
    reference = model.state_dict()
    if codec == "zlib-f32-v1":
        count = sum(v.numel() for v in reference.values())
        if not isinstance(values, str) or len(values) > count * 12 + 512:
            raise ValueError("Packed state exceeds expected model size")
        try:
            compressed = base64.b64decode(values, validate=True)
            decoder = zlib.decompressobj()
            raw = decoder.decompress(compressed, count * 4 + 1)
            if len(raw) != count * 4 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError("Packed state length mismatch")
            flat = struct.unpack(f"<{count}f", raw)
            values, offset = {}, 0
            for key, ref in reference.items():
                size = ref.numel()
                values[key] = torch.tensor(flat[offset:offset+size]).reshape(ref.shape).tolist()
                offset += size
        except (zlib.error, struct.error, TypeError) as exc:
            raise ValueError("Invalid packed model") from exc
    elif codec != "json":
        raise ValueError("Unsupported model state codec")
    if not isinstance(values, dict):
        raise ValueError("Model state must contain named tensors")
    if set(values) != set(reference):
        raise ValueError("Model parameter keys mismatch")
    state = {}
    for key, ref in reference.items():
        value = torch.tensor(values[key], dtype=ref.dtype)
        if value.shape != ref.shape or not torch.isfinite(value).all():
            raise ValueError(f"Invalid tensor: {key}")
        state[key] = value
    model.load_state_dict(state)
    return model


def predictions(model, rows):
    if not rows:
        return []
    with torch.no_grad():
        x = torch.tensor([encode(row) for row in rows], dtype=torch.float32)
        return torch.expm1(model(x).clamp(0, math.log1p(100000))).tolist()


def envelope(model, codec="json"):
    value = {"feature_version": FEATURE_VERSION, "target": TARGET,
             "model_family": model.family, "state": state_json(model)}
    if codec == "packed":
        flat = [float(v) for tensor in model.state_dict().values() for v in tensor.flatten().tolist()]
        value.update(state_codec="zlib-f32-v1", state=base64.b64encode(
            zlib.compress(struct.pack(f"<{len(flat)}f", *flat), level=6)).decode("ascii"))
    elif codec != "json":
        raise ValueError("Unsupported transport codec")
    return value


def validate_envelope(value):
    if value["feature_version"] != FEATURE_VERSION or value["target"] != TARGET:
        raise ValueError("Checkpoint target/feature version mismatch")
    return load_state(value["state"], value.get("model_family", "residual_mlp"), value.get("state_codec", "json"))


def train(model, rows, epochs, lr, batch, seed, optimizer_name="auto", loss_name="auto"):
    torch.manual_seed(seed)
    x = torch.tensor([encode(row) for row in rows], dtype=torch.float32)
    y = torch.tensor([math.log1p(row["target_ms"]) for row in rows], dtype=torch.float32)
    generator = torch.Generator().manual_seed(seed)
    if optimizer_name == "auto":
        optimizer_name = "adam" if model.family == "trend" else "sgd"
    if loss_name == "auto":
        loss_name = "huber" if model.family == "trend" else "mse"
    optimizer = (torch.optim.Adam if optimizer_name == "adam" else torch.optim.SGD)(model.parameters(), lr=lr)
    for _ in range(epochs):
        order = torch.randperm(len(rows), generator=generator)
        for idx in order.split(batch):
            optimizer.zero_grad(set_to_none=True)
            estimated = model(x[idx])
            loss = nn.functional.smooth_l1_loss(estimated, y[idx], beta=.05) if loss_name == "huber" else nn.functional.mse_loss(estimated, y[idx])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
    return model


def errors(values, rows):
    diffs = [p - row["target_ms"] for p, row in zip(values, rows)]
    return {"count": len(diffs), "abs_sum": sum(abs(d) for d in diffs),
            "sq_sum": sum(d*d for d in diffs)}


def metrics(stats):
    count = sum(s["count"] for s in stats)
    if not count:
        return {"count": 0, "mae_ms": None, "rmse_ms": None}
    return {"count": count, "mae_ms": sum(s["abs_sum"] for s in stats) / count,
            "rmse_ms": math.sqrt(sum(s["sq_sum"] for s in stats) / count)}
