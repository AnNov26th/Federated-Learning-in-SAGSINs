"""Append experiments using verified, read-only existing client MySQL datasets."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from backend.main import acquire_coordinator_lock
from backend.database.database import SessionLocal
from backend.models.simulation import Experiment
from backend.services.fl_service import run_experiment
from sagsin.paths import OUTPUT
from sagsin.storage import read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', nargs='+', type=int, default=[13, 14, 15, 16, 17])
    parser.add_argument('--rounds', type=int, default=10, choices=range(1, 101))
    parser.add_argument('--selection', choices=['random', 'delay_aware', 'predictive'], default='random')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    destination = OUTPUT / 'retraining' / args.output
    if destination.exists():
        parser.error('Output already exists; choose a new run name')
    destination.mkdir(parents=True)
    results = []
    # The same MySQL advisory lock as the app prevents a concurrent coordinator.
    lock = acquire_coordinator_lock()
    try:
        for source_id in args.sources:
            with SessionLocal() as db:
                source = db.get(Experiment, source_id)
                if source is None or source.status != 'COMPLETED':
                    raise ValueError('Source must be a completed experiment')
                config = deepcopy(source.config_json)
                if config.get('runtime') != 'federated-http-v3':
                    raise ValueError('Source must use the distributed MySQL runtime')
                source_run = config['distributed_config'].get('dataset_run_id') or config['runtime_id']
                config['distributed_config'].update(dataset_run_id=source_run, rounds=args.rounds,
                                                     selection=args.selection)
                for key in ('distributed_result', 'training_progress', 'resume_requested', 'comparison_id'):
                    config.pop(key, None)
                config.update(runtime_id=uuid.uuid4().hex, rounds=args.rounds,
                              reused_from_experiment=source_id, dataset_read_only=True)
                row = Experiment(scenario_id=source.scenario_id,
                                 algorithm={'random': 'FedAvg', 'delay_aware': 'DelayAware', 'predictive': 'Predictive'}[args.selection],
                                 rounds=args.rounds, learning_rate=source.learning_rate,
                                 status='QUEUED', is_simulation=True, config_json=config)
                db.add(row)
                db.commit()
                identifier = row.id
            print(f'Start #{identifier}, source #{source_id}, existing data {source_run}, {args.selection}', flush=True)
            run_experiment(identifier)
            with SessionLocal() as db:
                row = db.get(Experiment, identifier)
                if row.status != 'COMPLETED':
                    raise RuntimeError(f'Experiment #{identifier}: {row.error_message}')
                result = read_json(OUTPUT / 'experiments' / config['runtime_id'] / 'result.json')
                record = dict(id=identifier, source_id=source_id, dataset_id=config['dataset_id'],
                              dataset_run_id=source_run, artifact_id=config['runtime_id'],
                              seed=config['seed'], selection=args.selection, rounds=args.rounds,
                              test=result['test'], communication=result['communication'],
                              client_fingerprints={c: h['dataset_sha256'] for c, h in result['clients'].items()},
                              finished_at=datetime.now(timezone.utc).isoformat())
                results.append(record)
                write_json(destination / 'runs.json', results)
                print(f"Completed #{identifier}: FL={result['test']['fl']['mae_ms']:.6f}, persistence={result['test']['persistence']['mae_ms']:.6f} ms", flush=True)
    finally:
        lock.close()


if __name__ == '__main__':
    main()
