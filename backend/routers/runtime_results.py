"""Original Results page access to versioned HTTP runtime artifacts."""
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from backend.database.database import get_db
from backend.models.simulation import Experiment
from backend.schemas.base import APIResponse
from backend.services.distributed_runtime_service import RUNTIME,directory
from sagsin.storage import read_json

router=APIRouter()


def folder(db,identifier):
    row=db.get(Experiment,identifier)
    if not row:raise HTTPException(404,"Experiment not found")
    if row.config_json.get("runtime")!=RUNTIME:raise HTTPException(409,"Experiment dùng runtime lịch sử")
    return directory(row.config_json)


@router.get("/experiments/{identifier}/outcomes")
def outcomes(identifier:int,db:Session=Depends(get_db)):
    root=folder(db,identifier)
    path=root/"result.json"
    if not path.exists():raise HTTPException(409,"Kết quả đang được tính")
    result=read_json(path)
    if (root/"offline-baseline.json").exists():result["offline_baseline"]=read_json(root/"offline-baseline.json")
    return APIResponse(data=result)


@router.get("/experiments/{identifier}/network/{policy}")
def network(identifier:int,policy:str,db:Session=Depends(get_db)):
    if policy not in {"static-equal","current-equal","fl-equal","current-demand","current-minimax","fl-minimax","current-deadline","fl-deadline"}:
        raise HTTPException(404,"Unknown policy")
    path=folder(db,identifier)/"network"/(policy+".json")
    if not path.exists():raise HTTPException(409,"Kết quả mạng chưa sẵn sàng")
    return APIResponse(data=read_json(path))


@router.get("/experiments/{identifier}/checkpoint")
def checkpoint(identifier:int,db:Session=Depends(get_db)):
    path=folder(db,identifier)/"checkpoint.json"
    if not path.exists():raise HTTPException(409,"Chưa có checkpoint")
    return FileResponse(path,filename=f"experiment-{identifier}-checkpoint.json")
