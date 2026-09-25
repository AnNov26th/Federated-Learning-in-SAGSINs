from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from backend.database.database import engine
from sqlalchemy import text
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(
    title="Federated Learning in SAGSINs",
    version="0.1.0"
)

from backend.routers import network, participants, simulations, dashboard

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(network.router, prefix="/api", tags=["Network"])
app.include_router(participants.router, prefix="/api/participants", tags=["Participants"])
app.include_router(simulations.router, prefix="/api/simulations", tags=["Simulations"])

@app.get("/api/health")
def health():
    return {"status": "ok", "message": "SAGSIN Backend is running"}

@app.get("/api/system")
def system_info():
    return {
        "name": "Federated Learning in SAGSINs",
        "version": "0.1.0",
        "components": ["Space", "Air", "Ground", "Sea"]
    }

@app.get("/api/test-db")
def test_db():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT DATABASE()"))
            db_name = result.scalar()
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
app.mount("/css", StaticFiles(directory="frontend/css"), name="css")
app.mount("/js", StaticFiles(directory="frontend/js"), name="js")
app.mount("/assets", StaticFiles(directory="frontend/assets"), name="assets")
app.mount("/", StaticFiles(directory="frontend/html", html=True), name="frontend")