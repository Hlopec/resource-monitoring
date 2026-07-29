# resource-monitoring
Platform for automated discovery, monitoring, vulnerability assessment, and security analytics of Internet-facing IT resources.

## Project purpose
This repository is being prepared as a local development workspace for a resource monitoring platform. The current focus is to establish the initial project structure for future API, worker, collector, database, integration, and infrastructure components.

## Current development stage
The project is currently in Stage 01.3: base Docker Compose environment. This stage introduces a minimal local development stack with an API service, PostgreSQL, and Redis.

## Prerequisites
- macOS with Apple Silicon
- Colima running with Docker support
- Docker Engine and Docker Compose

## Environment setup
1. Copy the example environment file: `cp .env.example .env`
2. Review the local-development defaults in `.env.example` before starting the stack.

## Start the stack
- Validate the Compose configuration: `docker compose config`
- Build the images: `docker compose build`
- Start the stack: `docker compose up -d`
- Check service status: `docker compose ps`

## Service overview
- `api`: FastAPI application on port `8000` with root and health endpoints
- `postgres`: PostgreSQL 16 with a named persistent volume and health checks
- `redis`: Redis 7 with a named persistent volume and health checks

## API checks
- Root endpoint: `curl --fail http://localhost:8000/`
- Health endpoint: `curl --fail http://localhost:8000/health`
- Logs: `docker compose logs --no-color api`

## Database and Redis checks
- PostgreSQL readiness: `docker compose exec postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"`
- Redis ping: `docker compose exec redis redis-cli ping`

## Stop the stack
- Stop containers: `docker compose down`
- Remove local data volumes as well: `docker compose down -v`

## Named volumes
The Compose stack uses named volumes for PostgreSQL and Redis data. The `docker compose down -v` command removes those volumes and deletes local database and Redis data.

## Deferred functionality
Database integration in application code, Redis integration beyond basic service startup, workers, collectors, DefectDojo, monitoring, authentication, ORM, migrations, and business logic remain deferred beyond this stage.
