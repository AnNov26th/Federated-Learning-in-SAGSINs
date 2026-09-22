from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Federated Learning in SAGSINs",
    version="0.1.0"
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "message": "SAGSIN Backend is running"
    }


@app.get("/api/system")
def system_info():
    return {
        "name": "Federated Learning in SAGSINs",
        "version": "0.1.0",
        "components": [
            "Space",
            "Air",
            "Ground",
            "Sea"
        ]
    }


from sqlalchemy import text
from backend.database.database import engine

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
app.mount(
    "/css",
    StaticFiles(directory="frontend/css"),
    name="css"
)

app.mount(
    "/js",
    StaticFiles(directory="frontend/js"),
    name="js"
)

app.mount(
    "/assets",
    StaticFiles(directory="frontend/assets"),
    name="assets"
)


from backend.database.database import SessionLocal
from backend.models.network import Node

@app.get("/api/nodes")
def get_nodes():
    db = SessionLocal()
    try:
        nodes = db.query(Node).all()
        return {"status": "success", "data": nodes}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        db.close()

# HTML
app.mount(
    "/",
    StaticFiles(
        directory="frontend/html",
        html=True
    ),
    name="frontend"
)