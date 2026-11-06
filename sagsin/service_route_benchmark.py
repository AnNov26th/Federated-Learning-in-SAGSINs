"""Paired static/current/FL routing on held-out dynamic-contact windows.

Reads completed FL runs. Does not retrain, mutate topology or use future data
for decisions. Future frames are only used to score the selected paths.
"""
import argparse, csv, html, json, random, statistics, urllib.request, hashlib
from pathlib import Path
from types import SimpleNamespace
import torch
from backend.models.network import Node,NetworkLink
from backend.services.service_routing_service import build_frame,route,refresh_route,accept_change
from sagsin.model import validate_envelope
from sagsin.allocation import allocate,assert_capacity
from sagsin.paths import OUTPUT,ROOT
from sagsin.storage import read_json,write_json

POLICIES=('static','current','predictive')

def evaluate(inventory,links,result,checkpoint,seconds=45,pairs_count=3,*,
             profile=None,capacity_scale=1.,fail_links=False,handover_pause=0.,
             service='Video Call',device='network_gateway'):
    from backend.services.routing_service import SERVICES,APPLICATION_PROFILES
    from backend.services.event_device_service import DEVICES
    if device!='network_gateway' and device not in DEVICES:raise ValueError('Unknown benchmark device')
    config=dict(result['config']);model=validate_envelope(checkpoint['model']);seed=config['seed']
    if profile is not None:config['profile']=profile
    demand=SERVICES[service]['min_bandwidth'];budget=APPLICATION_PROFILES[service]['latency_budget_ms']
    if seconds<1 or pairs_count<1 or not 0<capacity_scale<=1 or not 0<=handover_pause<=1:
        raise ValueError('Invalid benchmark window, pair count, capacity or pause')
    grounds=[n for n in inventory if n.type=='GROUND' and n.status=='ACTIVE']
    rng=random.Random(seed);pairs=[]
    for index in range(pairs_count):
        a,b=rng.sample(grounds,2)
        pairs.append((SimpleNamespace(id=index*2,lat=a.lat,lng=a.lng,device=device),
                      SimpleNamespace(id=index*2+1,lat=b.lat,lng=b.lng,device=device)))
    states={p:[dict(routes=[],last_switch=-100,last_review=-100) for _ in pairs] for p in POLICIES}
    stats={p:dict(seed=seed,policy=p,cases=0,available=0,qos_met=0,handovers=0,delivered_mbit=0.,capacity_violations=0) for p in POLICIES}
    delays={p:[] for p in POLICIES};stretches={p:[] for p in POLICIES};errors={p:[] for p in POLICIES}
    first=config['samples_per_client']+20
    def stress(frame):
        # A declared deterministic outage, visible at decision time. No future leak.
        for key,edge in list(frame['edges'].items()):
            edge['bandwidth_mbps']*=capacity_scale
            edge['features']['bandwidth_mbps']*=capacity_scale
            digest=hashlib.sha256(('|'.join(sorted(key))+str(seed)).encode()).digest()
            if fail_links and first+seconds//3<=frame['now']<first+2*seconds//3 and digest[0]<64:
                del frame['edges'][key]
        return frame
    for tick in range(first,first+seconds):
        frame=stress(build_frame(inventory,links,tick,config,model,{'experiment_id':'paired-model'}))
        future=stress(build_frame(inventory,links,tick+1,config))
        for key,edge in frame['edges'].items():
            if key not in future['edges']:continue
            target=future['edges'][key]['current_ms']
            for p,field in [('static','static_ms'),('current','current_ms'),('predictive','predicted_ms')]:errors[p].append(abs(edge[field]-target))
        for policy in POLICIES:
            actual=[];capacities={};realized={}
            for index,(a,b) in enumerate(pairs):
                item=states[policy][index];old=item['routes']
                current=[refresh_route(frame,r,source,target,service,policy) for r,source,target in zip(old,(a,b),(b,a))]
                valid=current if len(current)==2 and all(current) else []
                if not valid or tick-item['last_review']>=3:
                    candidates=[route(frame,a,b,service,policy)[0],route(frame,b,a,service,policy)[0]]
                    if all(candidates):
                        accepted,_=accept_change(valid,candidates,tick,item['last_switch'])
                        if accepted:
                            if old and [r['path'] for r in old]!=[r['path'] for r in candidates]:stats[policy]['handovers']+=1
                            valid=candidates;item['last_switch']=tick
                    item['last_review']=tick
                item['routes']=valid
                scored=[refresh_route(future,r,source,target,service,'current') for r,source,target in zip(valid,(a,b),(b,a))]
                stats[policy]['cases']+=1
                if len(scored)!=2 or not all(scored):continue
                realized[index]=scored
                for direction,r in enumerate(scored):
                    path=[]
                    for node in r['path']:
                        key='node:'+node;capacities[key]=future['nodes'][node].bandwidth;path.append(key)
                    for hop in r['hops']:
                        key='link:'+str(hop['link_id']);capacities[key]=hop['bandwidth_mbps'];path.append(key)
                    source,target=(a,b) if direction==0 else (b,a)
                    for client,capacity in ((source,r['sourceCapacityMbps']),(target,r['receiver_capacity_mbps'])):
                        key=f'access:{client.id}';capacities[key]=min(capacities.get(key,capacity),capacity);path.append(key)
                    key=f'demand:{index}:{direction}';capacities[key]=demand;path.append(key)
                    actual.append(dict(id=index*2+direction,path=path,remaining_mbit=demand))
            rates=allocate(actual,capacities,'equal');assert_capacity(actual,rates,capacities)
            for index,scored in realized.items():
                stats[policy]['available']+=1
                values=[rates[index*2],rates[index*2+1]];rate=min(values)
                # Lost service time is charged on initial setup and every accepted switch.
                fraction=1-handover_pause if states[policy][index]['last_switch']==tick else 1.
                stats[policy]['delivered_mbit']+=sum(values)*fraction
                latency=max(r['application']['estimated_one_way_ms'] for r in scored)
                delays[policy].append(latency);stretches[policy].append(max(r['path_stretch'] for r in scored))
                if rate*fraction>=demand-1e-7 and latency<=budget:stats[policy]['qos_met']+=1
        if (tick-first)%15==0:print(f'seed {seed}: dynamic tick {tick-first}/{seconds}',flush=True)
    rows=[]
    for policy in POLICIES:
        row=stats[policy]
        row.update(availability_fraction=row['available']/row['cases'],qos_fraction=row['qos_met']/row['cases'],
            delivery_fraction=row['delivered_mbit']/(2*demand*row['cases']),
            throughput_mbps=row['delivered_mbit']/seconds,
            mean_one_way_ms=statistics.mean(delays[policy]) if delays[policy] else None,
            mean_path_stretch=statistics.mean(stretches[policy]) if stretches[policy] else None,
            next_tick_link_mae_ms=statistics.mean(errors[policy]) if errors[policy] else None)
        rows.append(row)
    return rows,[dict(a=vars(a),b=vars(b)) for a,b in pairs]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('benchmark_directory',type=Path)
    parser.add_argument('--url',default='http://127.0.0.1:8000');parser.add_argument('--ticks',type=int,default=45)
    args=parser.parse_args();torch.set_num_threads(1)
    def api(path):
        with urllib.request.urlopen(args.url+path,timeout=30) as response:return json.load(response)['data']
    nodes=api('/api/nodes');counts={}
    for n in nodes:counts[n['scenario_id']]=counts.get(n['scenario_id'],0)+1
    scenario=max(counts,key=counts.get);nodes=[n for n in nodes if n['scenario_id']==scenario]
    ids={n['id'] for n in nodes};links=[l for l in api('/api/links') if l['source'] in ids and l['target'] in ids]
    destination=args.benchmark_directory/'dynamic-services';destination.mkdir(parents=True,exist_ok=True)
    write_json(destination/'inventory.json',dict(scenario_id=scenario,nodes=nodes,links=links))
    inventory=[Node(**{k:v for k,v in row.items() if k in Node.__table__.columns.keys()}) for row in nodes]
    stored=[NetworkLink(**{k:v for k,v in row.items() if k in NetworkLink.__table__.columns.keys()}) for row in links]
    records=read_json(args.benchmark_directory/'runs.json');rows=[];workloads={}
    for record in records:
        root=OUTPUT/'experiments'/record['artifact_id'];result=read_json(root/'result.json');checkpoint=read_json(root/'checkpoint.json')
        values,pairs=evaluate(inventory,stored,result,checkpoint,args.ticks)
        rows.extend(values);workloads[str(record['seed'])]=pairs
        write_json(destination/'runs.json',rows);write_json(destination/'workloads.json',workloads)
    aggregates=[]
    metrics=('availability_fraction','qos_fraction','mean_one_way_ms','mean_path_stretch','next_tick_link_mae_ms','handovers','delivered_mbit')
    for policy in POLICIES:
        group=[r for r in rows if r['policy']==policy];aggregate=dict(policy=policy,seeds=len(group))
        for key in metrics:
            values=[r[key] for r in group if r[key] is not None]
            aggregate[key+'_mean']=statistics.mean(values) if values else None
            aggregate[key+'_std']=statistics.stdev(values) if len(values)>1 else 0
        aggregates.append(aggregate)
    write_json(destination/'aggregates.json',aggregates)
    paired=[]
    for seed in sorted({row['seed'] for row in rows}):
        current=next(r for r in rows if r['seed']==seed and r['policy']=='current')
        fl=next(r for r in rows if r['seed']==seed and r['policy']=='predictive')
        paired.append(dict(seed=seed,mae_improvement_ms=current['next_tick_link_mae_ms']-fl['next_tick_link_mae_ms'],
                           qos_change=fl['qos_fraction']-current['qos_fraction']))
    write_json(destination/'paired.json',paired)
    inputs=ROOT/'storage/input/service_benchmarks'/args.benchmark_directory.name
    write_json(inputs/'inventory.json',dict(scenario_id=scenario,nodes=nodes,links=links))
    write_json(inputs/'workloads.json',workloads)
    for name,values in [('runs',rows),('aggregates',aggregates)]:
        with (destination/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    def table(values):
        keys=list(values[0]);return '<table><tr>'+''.join(f'<th>{html.escape(k)}</th>' for k in keys)+'</tr>'+''.join('<tr>'+''.join(f'<td>{html.escape(str(r[k]))}</td>' for k in keys)+'</tr>' for r in values)+'</table>'
    (destination/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Dynamic SAGSIN paired benchmark</title><style>body{font:14px Segoe UI;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:8px}section{overflow:auto}</style><h1>Đối chứng FL trên mạng động</h1><p>Cùng seed, topology, client pair và cửa sổ tương lai; model đóng băng trước đánh giá. Chọn tại t, chấm tại t+1. QoS cần cả hai chiều ≥2 Mbps và ≤150 ms; tỷ lệ tính trên mọi trường hợp, không chỉ lượt thành công. Mean độ trễ chỉ tính tuyến còn khả dụng, cần đọc cùng availability. Chuyển động và tải synthetic; không suy ra QoS ngoài thực địa hoặc ưu thế thống kê từ 5 seed.</p><section>'+table(aggregates)+'</section><h2>Từng seed</h2><section>'+table(rows)+'</section>',encoding='utf-8')
    print(destination/'report.html',flush=True)
    write_json(destination/'methodology.json',dict(complete=True,seeds=sorted({r['seed'] for r in records}),
        experiment_ids=[r['id'] for r in records],ticks=args.ticks,client_pairs=3,scenario_id=scenario,
        information_time='t',evaluation_time='t+1',profile=read_json(OUTPUT/'experiments'/records[0]['artifact_id']/'result.json')['config']['profile'],
        inventory_sha256=hashlib.sha256((destination/'inventory.json').read_bytes()).hexdigest(),
        routing_sha256=hashlib.sha256((ROOT/'backend/services/service_routing_service.py').read_bytes()).hexdigest()))

if __name__=='__main__':main()
