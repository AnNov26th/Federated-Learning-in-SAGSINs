"""MNIST loading and deterministic, exhaustive client partitions."""
import os

import numpy as np
from torch.utils.data import Subset
from torchvision import datasets, transforms


class MNISTDatasetManager:
    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "input", "mnist"))
        self.data_dir = data_dir
        self.transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.1307,), (0.3081,)),
        ])
        self.train_dataset = None
        self.test_dataset = None

    def load_data(self):
        self.train_dataset = datasets.MNIST(root=self.data_dir, train=True, download=True, transform=self.transform)
        self.test_dataset = datasets.MNIST(root=self.data_dir, train=False, download=True, transform=self.transform)
        return self.train_dataset, self.test_dataset

    def partition_iid(self, num_clients, seed=42):
        self._ensure_data()
        if num_clients < 1 or num_clients > len(self.train_dataset):
            raise ValueError("num_clients must be between 1 and the number of training samples.")
        indices = np.random.default_rng(seed).permutation(len(self.train_dataset))
        return [Subset(self.train_dataset, chunk.tolist()) for chunk in np.array_split(indices, num_clients)]

    def partition_non_iid(self, num_clients, num_classes_per_client=2, seed=42):
        """Partition all samples into label-sorted shards assigned to clients."""
        self._ensure_data()
        if num_clients < 1 or num_clients > len(self.train_dataset):
            raise ValueError("num_clients must be between 1 and the number of training samples.")
        labels = np.asarray(self.train_dataset.targets)
        rng = np.random.default_rng(seed)
        indices = np.arange(len(labels))
        # Shards preserve label skew while assigning every training example once.
        ordered = indices[np.argsort(labels, kind="stable")]
        shard_count = min(max(num_clients * max(1, num_classes_per_client), num_clients), len(ordered))
        shards = [chunk for chunk in np.array_split(ordered, shard_count) if len(chunk)]
        shard_order = rng.permutation(len(shards)).tolist()
        client_shards = [[] for _ in range(num_clients)]
        for shard_index, position in enumerate(shard_order):
            client_shards[shard_index % num_clients].extend(shards[position].tolist())
        return [Subset(self.train_dataset, shard_indices) for shard_indices in client_shards]

    def _ensure_data(self):
        if self.train_dataset is None or self.test_dataset is None:
            self.load_data()
