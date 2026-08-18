from fastapi import FastAPI

from app.api import include_api_routes
from app.api.errors import register_application_error_handlers

app = FastAPI(title="resource-monitoring-api")
register_application_error_handlers(app)
include_api_routes(app)
