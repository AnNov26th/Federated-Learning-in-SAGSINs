"""Acceptance through A's original API, global snapshot and actual HTTP workers."""
import argparse,json,time,uuid,urllib.request
from sqlalchemy import text
import torch
from .paths import OUTPUT
from .storage import read_json,write_json
from .fedavg import FedAvg
from .model import validate_envelope

def verify_audit(directory):
    for path in sorted((directory/'audit').glob('*.json')):
        audit=read_json(path)
        expected=FedAvg.aggregate([validate_envelope(u['model']).state_dict() for u in audit['updates']], [u['samples'] for u in audit['updates']])
        actual=validate_envelope(audit['global_after']).state_dict()
        if any(not torch.equal(expected[k],actual[k]) for k in expected):raise AssertionError('FedAvg mismatch: '+str(path))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--scenario',type=int)
    parser.add_argument('--experiment',type=int)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    def api(path,body=None):
        req=urllib.request.Request(args.url+path,None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)['data']
    def wait(identifier,timeout=600):
        deadline=time.monotonic()+timeout;previous=None
        while time.monotonic()<deadline:
            value=api(f'/api/fl/experiments/{identifier}')
            state=(value['status'],value['completed_rounds'])
            if state!=previous:print(identifier,state,flush=True);previous=state
            if value['status'] in {'COMPLETED','FAILED','CANCELLED','INTERRUPTED'}:return value
            time.sleep(.5)
        raise TimeoutError('Global acceptance timed out')
    if args.experiment:run=wait(args.experiment)
    else:
        nodes=api('/api/nodes');counts={}
        for n in nodes:counts[n['scenario_id']]=counts.get(n['scenario_id'],0)+1
        scenario=args.scenario or max(counts,key=counts.get)
        run=api('/api/fl/experiments',dict(task='network_delay',scenario_id=scenario,pool_mode='all',algorithm='Predictive',
            rounds=2,client_count=min(24,counts[scenario]),samples_per_client=80,local_epochs=1,partition='non_iid',timeout_ms=120000))
        run=wait(run['id'])
    assert run['status']=='COMPLETED',run['error_message']
    cfg=run['config'];root=OUTPUT/'experiments'/cfg['runtime_id']
    verify_audit(root)
    outcome=api(f"/api/fl/experiments/{run['id']}/outcomes")
    assert len(outcome['network'])==8
    assert all(row['capacity_violations']==0 for row in outcome['network'])
    assert len(outcome['clients'])==len(cfg['candidate_pool'])
    from backend.database.database import engine
    from .database import credentials,connect
    forbidden=credentials()['clients'][cfg['candidate_pool'][0]]['database']
    with engine.connect() as connection:
        try:connection.execute(text(f'SELECT COUNT(*) FROM `{forbidden}`.observations'))
        except Exception as exc:assert getattr(exc.orig,'args',[None])[0] in {1044,1142}
        else:raise AssertionError('Main app can read client DB')
    summary=dict(experiment_id=run['id'],scenario_id=run['scenario_id'],pool=len(cfg['candidate_pool']),
        nodes=len(cfg['distributed_config']['topology']['nodes']),links=len(cfg['distributed_config']['topology']['links']),
        completed_rounds=run['completed_rounds'],fedavg_audit='exact tensor equality',main_database_isolation='passed',
        network=outcome['network'],test=outcome['test'],resume='not requested')
    if args.resume:
        payload=dict(task='network_delay',scenario_id=run['scenario_id'],pool_mode='all',algorithm='Predictive',rounds=8,
            client_count=min(24,len(cfg['candidate_pool'])),samples_per_client=80,local_epochs=1,partition='non_iid',timeout_ms=120000)
        other=api('/api/fl/experiments',payload);identifier=other['id']
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            other=api(f'/api/fl/experiments/{identifier}')
            if other['completed_rounds']:break
            if other['status'] in {'FAILED','COMPLETED'}:raise AssertionError(other)
            time.sleep(.05)
        else:raise TimeoutError('No checkpoint')
        api(f'/api/fl/experiments/{identifier}/cancel',{})
        stopped=wait(identifier);assert stopped['status']=='CANCELLED',stopped
        api(f'/api/fl/experiments/{identifier}/resume',{})
        resumed=wait(identifier);assert resumed['status']=='COMPLETED',resumed
        verify_audit(OUTPUT/'experiments'/resumed['config']['runtime_id'])
        assert [r['round'] for r in resumed['rounds']]==list(range(1,9))
        summary['resume']=dict(experiment_id=identifier,retained_rounds=stopped['completed_rounds'],completed_rounds=8)
    write_json(OUTPUT/'acceptance'/'unified.json',summary)
    print(json.dumps(summary,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
