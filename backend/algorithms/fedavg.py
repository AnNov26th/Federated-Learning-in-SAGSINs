"""PyTorch implementation of the FedAvg aggregation step."""
from collections.abc import Mapping, Sequence

import torch


class FedAvg:
    """Weighted-average compatible client model state dictionaries."""

    @staticmethod
    def aggregate(local_states: Sequence[Mapping[str, torch.Tensor]], data_sizes: Sequence[int]):
        if not local_states or len(local_states) != len(data_sizes):
            raise ValueError("Each local model must have a matching sample count.")
        if any(size <= 0 for size in data_sizes):
            raise ValueError("Client sample counts must be positive.")

        reference_keys = tuple(local_states[0].keys())
        if any(tuple(state.keys()) != reference_keys for state in local_states[1:]):
            raise ValueError("Client models must have identical parameter keys and order.")

        total = sum(data_sizes)
        result = {}
        for key in reference_keys:
            reference = local_states[0][key]
            if any(state[key].shape != reference.shape for state in local_states[1:]):
                raise ValueError(f"Incompatible tensor shape for model parameter '{key}'.")
            if not torch.is_floating_point(reference) and not torch.is_complex(reference):
                result[key] = reference.clone()
                continue
            averaged = torch.zeros_like(reference)
            for state, size in zip(local_states, data_sizes):
                averaged.add_(state[key].to(device=averaged.device, dtype=averaged.dtype), alpha=size / total)
            result[key] = averaged
        return result
