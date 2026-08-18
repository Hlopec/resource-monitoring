"""Pydantic schemas owned by the HTTP transport layer."""

from pydantic import BaseModel, ConfigDict


class ApiSchema(BaseModel):
    """Base class for explicit transport schemas."""

    model_config = ConfigDict(from_attributes=False)


class RootResponse(ApiSchema):
    service: str
    status: str


class StatusResponse(ApiSchema):
    status: str
