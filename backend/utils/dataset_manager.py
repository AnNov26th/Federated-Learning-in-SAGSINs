import os
import numpy as np
import torch
from torchvision import datasets, transforms
from torch.utils.data import DataLoader, Dataset, Subset

class MNISTDatasetManager:
    def __init__(self, data_dir="../data/mnist"):
        self.data_dir = data_dir
        self.transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.1307,), (0.3081,))
        ])
        self.train_dataset = None
        self.test_dataset = None
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)

    def load_data(self):
        """Tải dữ liệu MNIST từ torchvision."""
        print(f"Loading MNIST dataset into {self.data_dir}...")
        self.train_dataset = datasets.MNIST(
            root=self.data_dir, train=True, download=True, transform=self.transform
        )
        self.test_dataset = datasets.MNIST(
            root=self.data_dir, train=False, download=True, transform=self.transform
        )
        print(f"Loaded {len(self.train_dataset)} training samples and {len(self.test_dataset)} testing samples.")

    def partition_iid(self, num_clients):
        """Phân chia dữ liệu theo dạng IID (Independent and Identically Distributed)."""
        if self.train_dataset is None:
            self.load_data()
            
        num_items = int(len(self.train_dataset) / num_clients)
        client_datasets = []
        all_idxs = np.arange(len(self.train_dataset))
        np.random.shuffle(all_idxs)
        
        for i in range(num_clients):
            idxs = all_idxs[i * num_items : (i + 1) * num_items]
            client_datasets.append(Subset(self.train_dataset, idxs))
            
        return client_datasets

    def partition_non_iid(self, num_clients, num_classes_per_client=2):
        """Phân chia dữ liệu theo dạng Non-IID (mỗi client chỉ có một số label nhất định)."""
        if self.train_dataset is None:
            self.load_data()

        # Lấy targets
        targets = self.train_dataset.targets.numpy()
        num_classes = 10
        
        # Nhóm index theo class
        class_idxs = {i: np.where(targets == i)[0] for i in range(num_classes)}
        for i in range(num_classes):
            np.random.shuffle(class_idxs[i])
            
        client_datasets = []
        
        # Phân phối class cho mỗi client
        for i in range(num_clients):
            # Chọn ngẫu nhiên num_classes_per_client cho client này
            classes = np.random.choice(num_classes, num_classes_per_client, replace=False)
            idxs = []
            for c in classes:
                # Lấy một phần dữ liệu của class c
                # Để đơn giản, chia đều số mẫu của class cho số lượng client có thể nhận class này
                # Ở đây ta lấy ngẫu nhiên 500 mẫu cho mỗi class (tùy chỉnh)
                num_samples = int(len(class_idxs[c]) / (num_clients * num_classes_per_client / num_classes))
                # Tránh lỗi nếu num_samples vượt quá số lượng còn lại
                num_samples = min(num_samples, len(class_idxs[c]))
                
                selected_idxs = class_idxs[c][:num_samples]
                class_idxs[c] = class_idxs[c][num_samples:] # Loại bỏ các mẫu đã lấy
                idxs.extend(selected_idxs)
                
            client_datasets.append(Subset(self.train_dataset, idxs))
            
        return client_datasets

if __name__ == "__main__":
    # Test script
    manager = MNISTDatasetManager(data_dir="f:/CNTT/PBL4 Dự án hệ điều hành và lập trình mạng/Federated Learning in SAGSINs/data/mnist")
    manager.load_data()
    
    print("\nTesting IID Partitioning (10 clients):")
    iid_parts = manager.partition_iid(10)
    for i, part in enumerate(iid_parts):
        print(f"Client {i}: {len(part)} samples")
        
    print("\nTesting Non-IID Partitioning (10 clients, 2 classes each):")
    non_iid_parts = manager.partition_non_iid(10, 2)
    for i, part in enumerate(non_iid_parts):
        # Lấy label để kiểm chứng (lấy 10 mẫu đầu tiên)
        sample_labels = [manager.train_dataset.targets[idx].item() for idx in part.indices[:10]]
        print(f"Client {i}: {len(part)} samples, Sample labels: {set(sample_labels)}")
