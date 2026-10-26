from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from backend.database.database import engine
from backend.database.init_db import init_db
from sqlalchemy import text
import asyncio
import contextlib


@asynccontextmanager
async def lifespan(application):
    application.state.database_ready = False
    lock_connection=None
    clock_task=None
    try:
        if engine.dialect.name=="mysql":
            lock_connection=engine.connect()
            acquired=lock_connection.execute(text("SELECT GET_LOCK(:key,0)"),{"key":f"{engine.url.database}_coordinator"}).scalar()
            if acquired!=1:raise RuntimeError("Một backend khác đang điều phối database này. Chỉ chạy một server/worker.")
        await run_in_threadpool(init_db, bind=engine)
        def recover_training():
            from sqlalchemy.orm import Session
            from backend.services.distributed_runtime_service import recover
            with Session(engine) as db:recover(db)
        await run_in_threadpool(recover_training)
        application.state.database_ready = True
        from backend.services.research_flow_service import run_clock
        clock_task=asyncio.create_task(run_clock(engine))
        yield
    finally:
        if clock_task:
            clock_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await clock_task
        if lock_connection:
            try:lock_connection.execute(text("SELECT RELEASE_LOCK(:key)"),{"key":f"{engine.url.database}_coordinator"})
            finally:lock_connection.close()
        application.state.database_ready = False

app = FastAPI(
    title="Federated Learning in SAGSINs",
    version="0.3.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def revalidate_frontend(request, call_next):
    if request.method in {"POST","PUT","PATCH","DELETE"}:
        origin=request.headers.get("origin")
        if origin and origin!=f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail":"Cross-origin mutation rejected"},status_code=403)
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html") or path.startswith(("/css/", "/js/")):
        response.headers["Cache-Control"] = "no-cache"
    return response

from backend.routers import network, participants, simulations, dashboard, federated_learning, network_learning, routing, training_monitor

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(federated_learning.router, prefix="/api/fl", tags=["Federated Learning"])
app.include_router(training_monitor.router, prefix="/api/fl", tags=["Training monitor"])
from backend.routers import runtime_results
app.include_router(runtime_results.router,prefix="/api/fl",tags=["Network outcomes"])
from backend.routers import research
app.include_router(research.router,prefix="/api/research",tags=["Regional research"])
app.include_router(network_learning.router, prefix="/api/fl", tags=["Network prediction"])
app.include_router(network.router, prefix="/api", tags=["Network"])
app.include_router(routing.router, prefix="/api/routing", tags=["Predictive routing"])
app.include_router(participants.router, prefix="/api/participants", tags=["Participants"])
app.include_router(simulations.router, prefix="/api/simulations", tags=["Simulations"])

@app.get("/api/health")
def health():
    return {"status": "ok", "message": "SAGSIN Backend is running",
            "database_ready": getattr(app.state, "database_ready", False)}

@app.get("/api/system")
def system_info():
    return {
        "name": "Federated Learning in SAGSINs",
        "version": app.version,
        "components": ["Space", "Air", "Ground", "Sea"],
        "learning_tasks": ["network_delay", "mnist"],
        "network_schedulers": ["FedAvg", "DelayAware", "Predictive"],
        "distributed_fl": {"client_transport": "http-loopback", "topology": "scenario_snapshot",
                           "experiment_api": "/api/fl/experiments"},
    }

@app.get("/api/test-db")
def test_db():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            db_name = engine.url.database or "in-memory"
            return {
                "status": "success",
                "message": "Kết nối Database thành công!",
                "database": db_name
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Lỗi kết nối Database: {str(e)}"
        }

# Static files
frontend = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/css", StaticFiles(directory=frontend / "css"), name="css")
app.mount("/js", StaticFiles(directory=frontend / "js"), name="js")
app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
app.mount("/", StaticFiles(directory=frontend / "html", html=True), name="frontend")
# uvicorn backend.main:app --reload
