"""Local simulator clients use WebSocket for registration, heartbeats and signaling."""
import asyncio
import secrets
import time
from copy import deepcopy
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from backend.database.database import get_db, SessionLocal
from backend.models.service_session import ServiceClient, ServiceSession
from backend.schemas.service_session import ClientCreate, SessionCreate
from backend.services import service_session_service as service
from backend.services.fluid_network_service import clock_for
from backend.routers.routing import _lock_scenario

router=APIRouter()


def completed_benchmark(scenario_id=None):
    from sagsin.paths import OUTPUT
    from sagsin.storage import read_json
    for marker in sorted((OUTPUT/'benchmarks').glob('*/dynamic-services/methodology.json'),reverse=True):
        metadata=read_json(marker)
        if metadata.get('complete') and (scenario_id is None or metadata.get('scenario_id')==scenario_id):return marker.parent,metadata
    return None,None


@router.get('/benchmark')
def benchmark_summary(scenario_id:int=Query(ge=1)):
    from sagsin.storage import read_json
    directory,metadata=completed_benchmark(scenario_id)
    if directory is None:return {'available':False}
    return dict(available=True,run=directory.parent.name,seeds=len(metadata['seeds']),
                aggregates=read_json(directory/'aggregates.json'),methodology=metadata)


@router.get('/benchmark/report')
def benchmark_report(run:str):
    import re
    from sagsin.paths import OUTPUT
    from fastapi.responses import FileResponse
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z',run):raise HTTPException(404,'Báo cáo không tồn tại.')
    root=OUTPUT/'benchmarks'/run/'dynamic-services'
    if not (root/'methodology.json').is_file() or not (root/'report.html').is_file():raise HTTPException(404,'Báo cáo chưa hoàn tất.')
    return FileResponse(root/'report.html',media_type='text/html')


def snapshot(db, scenario_id):
    clients=db.query(ServiceClient).filter_by(scenario_id=scenario_id,deleted=False).order_by(ServiceClient.id).all()
    identifiers=[c.id for c in clients]
    sessions=db.query(ServiceSession).filter_by(scenario_id=scenario_id).filter(
        ServiceSession.source_id.in_(identifiers),
        (ServiceSession.target_id.is_(None))|ServiceSession.target_id.in_(identifiers))
    return dict(clients=[service.client_view(c) for c in clients],
                sessions=[service.session_view(s) for s in sessions.order_by(ServiceSession.id.desc()).limit(100)])


@router.get('/state')
def state(scenario_id:int=Query(ge=1), db:Session=Depends(get_db)):
    return snapshot(db,scenario_id)


@router.post('/clients',status_code=201)
def create_client(request:ClientCreate, db:Session=Depends(get_db)):
    _lock_scenario(db,request.scenario_id)
    if db.query(ServiceClient).filter_by(scenario_id=request.scenario_id,deleted=False).count()>=50:
        raise HTTPException(409,'Tối đa 50 client dịch vụ trong một scenario demo.')
    client=ServiceClient(**request.model_dump(),token=secrets.token_hex(24),last_seen=0)
    db.add(client);clock_for(db,request.scenario_id);db.commit();db.refresh(client)
    return service.client_view(client)


@router.delete('/clients/{client_id}')
def remove_client(client_id:int,db:Session=Depends(get_db)):
    client=db.get(ServiceClient,client_id)
    if not client:raise HTTPException(404,'Client không tồn tại.')
    _lock_scenario(db,client.scenario_id)
    db.refresh(client)
    sessions=db.query(ServiceSession).filter((ServiceSession.source_id==client_id)|(ServiceSession.target_id==client_id)).all()
    for session in sessions:
        if session.state in service.TERMINAL:continue
        session.state='ended'
        result=deepcopy(session.result_json)
        result.update(rates_mbps=[],reason='Client đã bị xóa; phiên đã kết thúc và trả băng thông.',closed_reason='client_deleted')
        session.result_json=result
    # Hide endpoints from the simulator while preserving FK/session audit data.
    client.deleted=True;client.last_seen=0
    db.commit()
    return {'deleted':True,'id':client_id}


def command(client_id,token,message):
    with SessionLocal() as db:
        client=db.get(ServiceClient,client_id)
        if not client or client.deleted or not secrets.compare_digest(client.token,token):raise HTTPException(403,'Client đã bị xóa hoặc sai danh tính.')
        _lock_scenario(db,client.scenario_id)
        client.last_seen=time.time()
        kind=message.get('type')
        response={}
        if kind=='start':
            request=SessionCreate(**message.get('request',{}))
            response={'session_id':service.create_session(db,client,request).id}
        elif kind in {'accept','reject','end'}:
            session=db.get(ServiceSession,message.get('session_id'))
            if not session:raise HTTPException(404,'Phiên không tồn tại.')
            service.action(db,client,session,kind)
        elif kind not in {'register','heartbeat'}:
            raise HTTPException(422,'Thông điệp không hợp lệ.')
        db.commit()
        return {'type':'state','request_id':message.get('request_id'),**response,**snapshot(db,client.scenario_id)}


def read_state(client_id,token):
    with SessionLocal() as db:
        client=db.get(ServiceClient,client_id)
        if not client or client.deleted or not secrets.compare_digest(client.token,token):raise HTTPException(403,'Client đã bị xóa hoặc sai danh tính.')
        return {'type':'state',**snapshot(db,client.scenario_id)}


@router.websocket('/clients/{client_id}/ws')
async def client_socket(websocket:WebSocket,client_id:int):
    origin=websocket.headers.get('origin')
    if origin and origin not in {f'http://{websocket.headers.get("host")}',f'https://{websocket.headers.get("host")}'}:
        await websocket.close(code=1008);return
    await websocket.accept()
    try:
        registration=await asyncio.wait_for(websocket.receive_json(),timeout=10)
        token=registration.get('token','')
        if registration.get('type')!='register' or not isinstance(token,str):
            await websocket.close(code=1008);return
        await websocket.send_json(await run_in_threadpool(command,client_id,token,{'type':'register'}))
        while True:
            try:
                message=await asyncio.wait_for(websocket.receive_json(),timeout=2)
            except asyncio.TimeoutError:
                await websocket.send_json(await run_in_threadpool(read_state,client_id,token));continue
            try:
                await websocket.send_json(await run_in_threadpool(command,client_id,token,message))
            except (HTTPException,ValueError,TypeError) as error:
                await websocket.send_json({'type':'error','request_id':message.get('request_id'),
                    'message':error.detail if isinstance(error,HTTPException) else 'Nội dung yêu cầu không hợp lệ.'})
    except (WebSocketDisconnect,asyncio.TimeoutError):
        pass
    except HTTPException:
        await websocket.close(code=1008)
