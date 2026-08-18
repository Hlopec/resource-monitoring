from fastapi import FastAPI

from app.api import include_api_routes

app = FastAPI(title="resource-monitoring-api")
include_api_routes(app)
