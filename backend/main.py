from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from backend.database.database import engine
from backend.database.init_db import init_db
from sqlalchemy import text


@asynccontextmanager
async def lifespan(application):
    application.state.database_ready = False
    # Add missing schema and apply versioned, additive inventory upgrades.
    # Existing topology, datasets, experiments and checkpoints survive reload.
    await run_in_threadpool(init_db, bind=engine)
    application.state.database_ready = True
    try:
        yield
    finally:
        application.state.database_ready = False

app = FastAPI(
    title="Federated Learning in SAGSINs",
    version="0.2.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def revalidate_frontend(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html") or path.startswith(("/css/", "/js/")):
        response.headers["Cache-Control"] = "no-cache"
    return response

from backend.routers import network, participants, simulations, dashboard, federated_learning, network_learning, routing

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(federated_learning.router, prefix="/api/fl", tags=["Federated Learning"])
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
