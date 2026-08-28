import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import copy


# 1. Định nghĩa Mạng Nơ-ron Tích chập (CNN) siêu nhẹ cho nút biên
class SimpleCNN(nn.Module):
    def __init__(self):
        super(SimpleCNN, self).__init__()
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        self.fc1 = nn.Linear(320, 50)
        self.fc2 = nn.Linear(50, 10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x), 2))
        x = F.relu(F.max_pool2d(self.conv2(x), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x


# 2. Hàm Huấn luyện Cục bộ (Local Training) trên UAV / Vệ tinh / Tàu biển
def train_local_model(model, dataloader, epochs=1, lr=0.01):
    """Huấn luyện mô hình trên dữ liệu cục bộ của 1 Client và trả về Trọng số mới"""
    local_model = copy.deepcopy(model)
    local_model.train()
    optimizer = optim.SGD(local_model.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(epochs):
        for data, target in dataloader:
            optimizer.zero_grad()
            output = local_model(data)
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()

    # Trả về bộ trọng số (state_dict) đã được học
    return local_model.state_dict()


# 3. Thuật toán Tổng hợp Trọng số FedAvg (Federated Averaging) tại Trạm mặt đất
def federated_averaging(weights_list):
    """Tính trung bình cộng các bộ trọng số nhận được từ các Client"""
    avg_weights = copy.deepcopy(weights_list[0])

    for key in avg_weights.keys():
        for i in range(1, len(weights_list)):
            avg_weights[key] += weights_list[i][key]
        avg_weights[key] = torch.div(avg_weights[key], len(weights_list))

    return avg_weights


if __name__ == "__main__":
    # Kiểm thử nhanh thuật toán FedAvg
    print("⏳ [Model/FL_Core] Đang kiểm thử khởi tạo mô hình và FedAvg...")
    global_model = SimpleCNN()
    dummy_weights_1 = global_model.state_dict()
    dummy_weights_2 = global_model.state_dict()

    new_global_weights = federated_averaging([dummy_weights_1, dummy_weights_2])
    print("✅ [Model/FL_Core] Thuật toán FedAvg và Mạng CNN đã sẵn sàng!")