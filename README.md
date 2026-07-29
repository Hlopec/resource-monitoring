# resource-monitoring
Platform for automated discovery, monitoring, vulnerability assessment, and security analytics of Internet-facing IT resources.

## Project purpose
This repository is being prepared as a local development workspace for a resource monitoring platform. The current focus is to establish the initial project structure for future API, worker, collector, database, integration, and infrastructure components.

## Current development stage
The project is currently in Stage 01.3: base Docker Compose environment. The initial Compose stack introduces the API, PostgreSQL, and Redis services for local development.

## Local development assumptions
The local environment is expected to run on macOS with Apple Silicon using Colima and Docker.

## Prerequisites
- Docker Engine and Docker Compose
- A local .env file created from .env.example

## Quick start
1. Copy the example environment file: `cp .env.example .env`
2. Validate the Compose configuration: `docker compose config`
3. Build the API image: `docker compose build`
4. Start the stack: `docker compose up -d`
5. Check service status: `docker compose ps`

## Service overview
- api: FastAPI service on port 8000
- postgres: PostgreSQL service with a persistent data volume
- redis: Redis service with a persistent data volume

## Health checks and validation
- API root: `curl --fail http://localhost:8000/`
- API health endpoint: `curl --fail http://localhost:8000/health`
- PostgreSQL readiness: `docker compose exec postgres pg_isready`
- Redis ping: `docker compose exec redis redis-cli ping`
- Logs: `docker compose logs --no-color api`
- Stop the stack: `docker compose down`

## Notes
Database integration, Redis integration in application code, workers, collectors, DefectDojo, and monitoring remain deferred beyond this stage.
