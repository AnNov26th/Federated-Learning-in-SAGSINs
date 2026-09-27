# MNIST FedAvg quick start

This implementation trains a small CNN on MNIST. The test split is held out and used to report global accuracy and loss after each round. Data partitions are reproducible from the configured random seed.

## Install and prepare the database

From the project root, install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set `DATABASE_URL` in `.env` to the project's MySQL connection string. Initialize missing tables, including the new per-client round table, without dropping existing data:

```powershell
python -m backend.database.init_db
```

The initializer uses SQLAlchemy `create_all`: it creates missing tables and does not alter or delete existing tables or rows. It is not a general schema migration tool.

Seed the SAGSIN topology only if the database has no scenario and nodes. `backend.database.seed_db` drops and recreates tables, and `backend.database.seed_fl` deletes existing FL experiment/participant rows before inserting demo metrics. Do not run either seeder against data you need to keep.

Start the API:

```powershell
uvicorn backend.main:app --reload
```

Open the app and choose **FL Training**, or visit `/fl.html`. The first training run loads and processes MNIST if needed. The dataset is stored under `data/mnist`.

## Experiment behavior

- `Centralized` trains on all MNIST training examples as a reference baseline.
- `FedAvg` splits all training examples across selected active participants, or chooses active topology nodes when none are selected.
- IID uses a seeded random split. Non-IID assigns label-sorted shards; both partitions include every training sample once.
- Round accuracy and loss are evaluated on MNIST's test set. Per-client status, sample count, local training metrics and transfer estimates are saved for each round.
- Latency, bandwidth, transfer time, dropout/timeout and energy are simulation estimates based on topology values. Local training time is measured on the host running this application, not on the represented SAGSIN device.
- Model weights stay in memory during a run and are not stored in MySQL. A server restart cannot resume an unfinished run.

Start with 2–3 rounds and 2–5 clients to check CPU performance before scaling up.
