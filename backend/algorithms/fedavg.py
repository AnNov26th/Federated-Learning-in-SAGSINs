class FedAvg:
    def __init__(self, global_model=None):
        self.global_model = global_model or {"weights": [0.0]*10}
        self.history = []

    def aggregate(self, local_models, data_sizes):
        """
        Federated Averaging Algorithm
        local_models: list of weight arrays from participants
        data_sizes: list of dataset sizes corresponding to each local model
        """
        if not local_models or not data_sizes:
            return self.global_model

        total_data = sum(data_sizes)
        num_params = len(self.global_model["weights"])
        new_weights = [0.0] * num_params
        
        for i, model in enumerate(local_models):
            weight_factor = data_sizes[i] / total_data
            for j in range(num_params):
                new_weights[j] += model[j] * weight_factor

        self.global_model["weights"] = new_weights
        return self.global_model

    def train_round(self, participants):
        """
        Simulate a training round
        """
        local_models = []
        data_sizes = []
        
        for p in participants:
            # Simulate local training by adding small random noise to global weights
            import random
            local_weights = [w + random.uniform(-0.1, 0.1) for w in self.global_model["weights"]]
            local_models.append(local_weights)
            data_sizes.append(p.get("dataset_size", 100))
            
        self.aggregate(local_models, data_sizes)
        
        # Calculate simulated accuracy/loss
        import math
        loss = sum(abs(w) for w in self.global_model["weights"]) # dummy loss
        accuracy = min(100, max(0, 100 - loss * 10)) # dummy accuracy
        
        result = {
            "accuracy": accuracy,
            "loss": loss
        }
        self.history.append(result)
        return result
