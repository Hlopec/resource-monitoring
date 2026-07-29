from fastapi import FastAPI

app = FastAPI(title="resource-monitoring-api")


@app.get("/")
def read_root() -> dict[str, str]:
    return {"service": "resource-monitoring-api", "status": "running"}


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "healthy"}
