"""Offline held-out stress matrix from saved checkpoints, without DB or training.

Replay packages contain only inventory, model checkpoints and config (no client
raw observations, credentials, service tokens or database dumps).
"""
import argparse
import csv
import hashlib
import html
import json
import random
import statistics
from pathlib import Path
import torch
from backend.models.network import Node, NetworkLink
from .service_route_benchmark import evaluate, POLICIES
from .storage import read_json, write_json
from .paths import ROOT, OUTPUT

CASES = [
    dict(name='normal', profile='normal', pairs=3, capacity_scale=1., fail_links=False, service='Video Call', device='network_gateway'),
    dict(name='concurrent_congested', profile='congested', pairs=12, capacity_scale=.25, fail_links=False, service='Video Call', device='network_gateway'),
    dict(name='mixed_outage', profile='mixed', pairs=6, capacity_scale=.5, fail_links=True, service='Video Call', device='network_gateway'),
    dict(name='gaming_outage', profile='mixed', pairs=6, capacity_scale=.5, fail_links=True, service='Gaming', device='network_gateway'),
    dict(name='smartphone_access', profile='normal', pairs=3, capacity_scale=1., fail_links=False, service='Video Call', device='smartphone'),
]
METRICS = ('availability_fraction', 'qos_fraction', 'delivery_fraction', 'throughput_mbps',
           'mean_one_way_ms', 'next_tick_link_mae_ms', 'handovers')


def paired_interval(values):
    """Seed is the sampling unit; ticks/links are correlated, never independent n."""
    if not values:
        return dict(n=0, mean=None, ci95=None)
    mean = statistics.mean(values)
    if len(values) < 2:
        return dict(n=len(values), mean=mean, ci95=None)
    rng = random.Random(20261031)
    draws = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(5000))
    return dict(n=len(values), mean=mean, ci95=[draws[125], draws[4874]])


def summarize(rows):
    aggregates = []
    paired = []
    for case in sorted({r['case'] for r in rows}):
        group = [r for r in rows if r['case'] == case]
        for policy in POLICIES:
            values = [r for r in group if r['policy'] == policy]
            item = dict(case=case, policy=policy, seeds=len(values))
            for metric in METRICS:
                valid = [r[metric] for r in values if r[metric] is not None]
                item[metric] = statistics.mean(valid) if valid else None
            aggregates.append(item)
        for baseline in ('static', 'current'):
            for metric in METRICS:
                deltas = []
                for seed in sorted({r['seed'] for r in group}):
                    a = next(r for r in group if r['seed'] == seed and r['policy'] == baseline)
                    b = next(r for r in group if r['seed'] == seed and r['policy'] == 'predictive')
                    if a[metric] is not None and b[metric] is not None:
                        deltas.append(b[metric] - a[metric])
                paired.append(dict(case=case, baseline=baseline, metric=metric,
                                   delta='FL minus baseline', **paired_interval(deltas)))
    return aggregates, paired


def prepare(source, destination):
    if destination.exists():raise ValueError('Refusing to overwrite a frozen input package')
    inventory = read_json(source / 'dynamic-services/inventory.json')
    write_json(destination / 'inventory.json', inventory)
    records = read_json(source / 'runs.json')
    if len({r['seed'] for r in records}) != len(records):
        raise ValueError('Select one training configuration per seed before packaging')
    for record in records:
        root = OUTPUT / 'experiments' / record['artifact_id']
        result = read_json(root / 'result.json')
        write_json(destination / 'models' / f"{record['seed']}.json",
                   dict(seed=record['seed'], experiment_id=record['id'], config=result['config'],
                        checkpoint=read_json(root / 'checkpoint.json')))
    write_json(destination / 'models.json', [dict(seed=r['seed'], experiment_id=r['id']) for r in records])
    write_json(destination / 'training-runs.json', records)
    write_json(destination / 'training-aggregates.json', read_json(source / 'aggregates.json'))


def table(rows):
    keys = list(rows[0])
    return '<table><tr>' + ''.join(f'<th>{html.escape(k)}</th>' for k in keys) + '</tr>' + ''.join(
        '<tr>' + ''.join(f'<td>{html.escape(str(r[k]))}</td>' for k in keys) + '</tr>' for r in rows) + '</table>'


def run(package, destination, ticks, cases):
    marker = destination / 'methodology.json'
    write_json(marker, dict(complete=False))
    saved = read_json(package / 'inventory.json')
    inventory = [Node(**{k:v for k,v in n.items() if k in Node.__table__.columns}) for n in saved['nodes']]
    links = [NetworkLink(**{k:v for k,v in n.items() if k in NetworkLink.__table__.columns}) for n in saved['links']]
    rows = []; workloads = {}
    models = read_json(package / 'models.json')
    for case in cases:
        for entry in models:
            model = read_json(package / 'models' / f"{entry['seed']}.json")
            values, pairs = evaluate(inventory, links, dict(config=model['config']), model['checkpoint'], ticks,
                case['pairs'], profile=case['profile'], capacity_scale=case['capacity_scale'],
                fail_links=case['fail_links'], handover_pause=.1, service=case['service'], device=case['device'])
            for row in values:
                row.update(case=case['name'], experiment_id=entry['experiment_id'])
            rows.extend(values); workloads[f"{case['name']}:{entry['seed']}"] = pairs
            write_json(destination / 'runs.json', rows)
            print(case['name'], entry['seed'], 'complete', flush=True)
    finish(package, destination, ticks, cases, rows, workloads, models)


def finish(package, destination, ticks, cases, rows, workloads, models, provenance=None):
    marker = destination / 'methodology.json'
    write_json(marker, dict(complete=False))
    aggregates, paired = summarize(rows)
    for name, values in [('aggregates', aggregates), ('paired', paired), ('runs', rows)]:
        write_json(destination / f'{name}.json', values)
        with (destination / f'{name}.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0])); writer.writeheader(); writer.writerows(values)
    write_json(destination / 'workloads.json', workloads)
    (destination / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>SAGSIN acceptance matrix</title>'
        '<style>body{font:14px system-ui;margin:24px}section{overflow:auto}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:6px}</style>'
        '<h1>SAGSIN: held-out stress matrix</h1><p>Frozen normal-trained models; mixed/congested are distribution shifts. '
        'Decision at t, scoring at t+1. Shared link/node/access capacity. 0.1 s setup/handover loss. '
        'Capacity scale represents residual reservations; it does not change synthetic delay labels. '
        'Outage removes a deterministic ~25% of undirected contacts during the middle third. '
        'Latency is max of both directions, conditional on availability. QoS and delivery include failures. '
        'Paired delta = FL minus baseline. Lower MAE/delay and higher delivery/QoS are better. '
        '95% percentile bootstrap resamples seeds (5000 draws); five seeds are exploratory, without multiple-comparison correction. '
        'No packet/RF/media or field QoS claim. Communication cost belongs to training report, not this offline replay.</p>'
        '<h2>Aggregates</h2><section>' + table(aggregates) + '</section><h2>Paired intervals</h2><section>' + table(paired) + '</section>', encoding='utf-8')
    hashes = {p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*.json'))}
    sources = {p:hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
        'sagsin/acceptance_matrix.py', 'sagsin/service_route_benchmark.py',
        'backend/services/service_routing_service.py', 'backend/services/network_motion_service.py')}
    write_json(marker, dict(complete=True, version=2, ticks=ticks, cases=cases, seeds=[m['seed'] for m in models],
        inputs_sha256=hashes, sources_sha256=sources, training_profile='normal', information_time='t', evaluation_time='t+1',
        handover_pause_s=.1, interval='paired seed percentile bootstrap, 5000 draws, seed=20261031',
        collected_from=provenance))
    print(destination / 'report.html', flush=True)


def collect(package, destination, ticks, cases, sources):
    """Consolidate seed groups saved by independent/interrupted local workers.

    Source hashes are retained. Incomplete workers may contribute only complete
    groups; the result must contain every requested seed/case/policy exactly once.
    """
    models = read_json(package / 'models.json')
    expected = {(c['name'],m['seed'],p):(c,m) for c in cases for m in models for p in POLICIES}
    rows = {}; workloads = {}; provenance = []
    for source in sources:
        saved = read_json(source / 'runs.json')
        provenance.append(dict(directory=str(source), runs_sha256=hashlib.sha256((source / 'runs.json').read_bytes()).hexdigest(),
                               source_complete=read_json(source / 'methodology.json').get('complete',False)))
        if (source / 'workloads.json').exists():workloads.update(read_json(source / 'workloads.json'))
        for row in saved:
            key = (row['case'],row['seed'],row['policy'])
            if key not in expected:raise ValueError(f'Unexpected group {key}')
            case, model = expected[key]
            if row['cases'] != ticks*case['pairs'] or row['experiment_id'] != model['experiment_id']:
                raise ValueError(f'Incompatible group {key}')
            if key in rows:raise ValueError(f'Duplicate group {key}')
            rows[key] = row
    if set(rows) != set(expected):raise ValueError('Missing seed/case/policy groups')
    for index, source in enumerate(sources):
        for name in ('runs.json', 'methodology.json'):
            target = destination / 'provenance' / str(index) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / name).read_bytes())
    inventory = read_json(package / 'inventory.json')
    grounds = [n for n in inventory['nodes'] if n['type']=='GROUND' and n['status']=='ACTIVE']
    for case in cases:
        for model in models:
            key = f"{case['name']}:{model['seed']}"
            if key in workloads:continue
            rng = random.Random(model['seed']); pairs = []
            for index in range(case['pairs']):
                a,b = rng.sample(grounds,2)
                pairs.append(dict(a=dict(id=index*2,lat=a['lat'],lng=a['lng'],device=case['device']),
                                  b=dict(id=index*2+1,lat=b['lat'],lng=b['lng'],device=case['device'])))
            workloads[key] = pairs
    finish(package,destination,ticks,cases,list(rows.values()),workloads,models,provenance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path, help='Existing completed training benchmark directory')
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--ticks', type=int, default=60)
    parser.add_argument('--cases', nargs='+', choices=[c['name'] for c in CASES])
    parser.add_argument('--collect', type=Path, nargs='+', help='Consolidate local seed-group outputs; preserve source hashes')
    args = parser.parse_args()
    if args.ticks < 3:parser.error('--ticks must be >= 3')
    if args.prepare:prepare(args.prepare, args.package)
    if args.output:
        if args.output.exists():parser.error('Output directory already exists; choose a new path')
        torch.set_num_threads(1)
        cases=[c for c in CASES if not args.cases or c['name'] in args.cases]
        if args.collect:collect(args.package,args.output,args.ticks,cases,args.collect)
        else:run(args.package, args.output, args.ticks, cases)


if __name__ == '__main__':
    main()
