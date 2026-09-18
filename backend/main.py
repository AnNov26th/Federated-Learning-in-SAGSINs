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


# HTML
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

# HTML
app.mount(
    "/",
    StaticFiles(
        directory="frontend/html",
        html=True
    ),
    name="frontend"
)