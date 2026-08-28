import torch
from torchvision import datasets, transforms
from torch.utils.data import DataLoader, Subset
import numpy as np

def load_non_iid_subsets():
    """Tải MNIST và chia thiên lệch (Non-IID) cho UAV, Satellite và Ship"""
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,))
    ])

    train_dataset = datasets.MNIST(root='./data', train=True, download=True, transform=transform)
    targets = np.array(train_dataset.targets)

    # Phân bổ nhãn thiên lệch
    uav_idx = np.where((targets == 0) | (targets == 1))[0]
    sat_idx = np.where((targets == 2) | (targets == 3))[0]
    ship_idx = np.where(targets >= 4)[0]

    loaders = {
        "UAV_01": DataLoader(Subset(train_dataset, uav_idx), batch_size=32, shuffle=True),
        "SAT_01": DataLoader(Subset(train_dataset, sat_idx), batch_size=32, shuffle=True),
        "SHIP_01": DataLoader(Subset(train_dataset, ship_idx), batch_size=32, shuffle=True)
    }

    print("✅ [Model/Dataset] Đã nạp và chia dữ liệu Non-IID thành công!")
    return loaders

if __name__ == "__main__":
    load_non_iid_subsets()