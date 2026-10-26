"""Multi-seed benchmark through A's original API and complete scenario topology."""
import argparse,json,time,urllib.request
from datetime import datetime,timezone
from itertools import product
from .paths import OUTPUT
from .storage import write_json,read_json
from .offline import centralized

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--scenario',type=int)
    parser.add_argument('--seeds',type=int,nargs='+',default=[11,42,71,101,137])
    parser.add_argument('--profiles',nargs='+',default=['normal'])
    parser.add_argument('--partitions',nargs='+',choices=['iid','non_iid'],default=['non_iid'])
    parser.add_argument('--selections',nargs='+',choices=['random','delay_aware','predictive'],default=['random'])
    parser.add_argument('--model-families',nargs='+',choices=['trend','residual_mlp'],default=['trend'])
    parser.add_argument('--transport-codecs',nargs='+',choices=['packed','json'],default=['packed'])
    parser.add_argument('--compare-upgrades',action='store_true')
    parser.add_argument('--rounds',type=int,default=5)
    parser.add_argument('--samples',type=int,default=240)
    parser.add_argument('--clients',type=int,default=24,help='Clients selected per round; the full pool/topology is retained')
    args=parser.parse_args()
    def api(path,body=None):
        request=urllib.request.Request(args.url+path,None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=120) as response:return json.load(response)['data']
    nodes=api('/api/nodes');counts={}
    for n in nodes:counts[n['scenario_id']]=counts.get(n['scenario_id'],0)+1
    scenario=args.scenario or max(counts,key=counts.get)
    destination=OUTPUT/'benchmarks'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    records=[]
    arms=[('residual_mlp','json'),('residual_mlp','packed'),('trend','packed')] if args.compare_upgrades else list(product(args.model_families,args.transport_codecs))
    for profile,partition,selection,(family,codec),seed in product(args.profiles,args.partitions,args.selections,arms,args.seeds):
        profile={'mixed':'bursty_congestion','congested':'low_bandwidth'}.get(profile,profile)
        job=api('/api/fl/experiments',dict(task='network_delay',scenario_id=scenario,pool_mode='all',
            algorithm={'random':'FedAvg','delay_aware':'DelayAware','predictive':'Predictive'}[selection],
            rounds=args.rounds,client_count=args.clients,samples_per_client=args.samples,partition=partition,
            network_profile=profile,seed=seed,model_family=family,transport_codec=codec,timeout_ms=120000))
        deadline=time.monotonic()+3600
        while time.monotonic()<deadline:
            run=api(f"/api/fl/experiments/{job['id']}")
            if run['status'] in {'COMPLETED','FAILED','CANCELLED','INTERRUPTED'}:break
            time.sleep(1)
        else:raise TimeoutError('Benchmark run timed out')
        if run['status']!='COMPLETED':raise RuntimeError(run['error_message'])
        root=OUTPUT/'experiments'/run['config']['runtime_id'];result=read_json(root/'result.json')
        offline=centralized(root)
        row=dict(id=run['id'],artifact_id=run['config']['runtime_id'],seed=seed,profile=profile,partition=partition,
            selection=selection,model_family=family,transport_codec=codec,
            fl_mae_ms=result['test']['fl']['mae_ms'],persistence_mae_ms=result['test']['persistence']['mae_ms'],
            linear_trend_mae_ms=result['test']['linear_trend']['mae_ms'],local_mae_ms=result['test']['local_only']['mae_ms'],
            centralized_mae_ms=offline['centralized']['mae_ms'],fl_json_bytes=offline['fl_all_json_bytes'],
            training_json_bytes=offline['fl_training_json_bytes'],savings_inclusive_fraction=offline['savings_inclusive_fraction'])
        records.append(row);write_json(destination/'runs.json',records)
        print(f"Experiment #{run['id']}: {family}/{codec}; pool={len(run['config']['candidate_pool'])}",flush=True)
    from .upgrade_benchmark import summarize
    print(summarize(destination,records),flush=True)

if __name__=='__main__':main()
