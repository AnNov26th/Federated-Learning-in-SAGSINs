"""Validation-only predictor development; never reads test targets for selection."""
import json
import torch
from .config import ExperimentConfig
from .dataset import generate
from .fedavg import FedAvg
from .model import DelayModel, errors, metrics, predictions, train
from .storage import write_json
from .topology import stable_seed
from .paths import OUTPUT


def main():
    torch.set_num_threads(1)
    results=[]
    for seed in (211,307):
        config=ExperimentConfig(seed=seed,samples_per_client=320,rounds=5)
        data={c:generate(c,config) for c in ("G1","A1","S1","SEA1")}
        validation=[r for rows in data.values() for r in rows if r["split"]=="validation"]
        for family in ("residual_mlp","trend"):
            torch.manual_seed(seed)
            model=DelayModel(family)
            for number in range(1,config.rounds+1):
                states,sizes=[],[]
                for client,rows in data.items():
                    local=DelayModel(family);local.load_state_dict(model.state_dict())
                    part=[r for r in rows if r["split"]=="train"]
                    train(local,part,config.local_epochs,config.learning_rate,config.batch_size,stable_seed(seed,client,number))
                    states.append(local.state_dict());sizes.append(len(part))
                model.load_state_dict(FedAvg.aggregate(states,sizes))
            record={"seed":seed,"model_family":family,"validation":metrics([errors(predictions(model,validation),validation)]),
                    "persistence":metrics([errors([r["observed_delay_ms"] for r in validation],validation)]),
                    "test_used_for_selection":False,"parameters":sum(p.numel() for p in model.parameters())}
            results.append(record)
            print(json.dumps(record),flush=True)
    write_json(OUTPUT / "development" / "predictor-validation.json",results)


if __name__=="__main__":main()
