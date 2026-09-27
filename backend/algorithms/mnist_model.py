import torch.nn as nn
import torch.nn.functional as F


class MNISTCNN(nn.Module):
    """Small CNN used as the first reproducible FL benchmark model."""
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 16, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, padding=1)
        self.pool = nn.MaxPool2d(2)
        self.fc1 = nn.Linear(32 * 7 * 7, 64)
        self.fc2 = nn.Linear(64, 10)

    def forward(self, inputs):
        inputs = self.pool(F.relu(self.conv1(inputs)))
        inputs = self.pool(F.relu(self.conv2(inputs)))
        inputs = inputs.flatten(1)
        inputs = F.relu(self.fc1(inputs))
        return self.fc2(inputs)
