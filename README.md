# resource-monitoring
Platform for automated discovery, monitoring, vulnerability assessment, and security analytics of Internet-facing IT resources.

## Project purpose
This repository is being prepared as a local development workspace for a resource monitoring platform. The current focus is to establish the initial project structure for future API, worker, collector, database, integration, and infrastructure components.

## Current development stage
The project is currently in Stage 02.0.2: Database Foundation. This stage adds the first PostgreSQL persistence layer for the Resource Inventory bounded context, including SQLAlchemy models, Alembic migrations, deterministic catalog seed data, and isolated database tests.

### Architecture documentation
- [docs/architecture/database/README.md](docs/architecture/database/README.md)
- [docs/architecture/database/domain-model.md](docs/architecture/database/domain-model.md)
- [docs/architecture/database/data-lifecycle.md](docs/architecture/database/data-lifecycle.md)
- [docs/architecture/database/indexing-strategy.md](docs/architecture/database/indexing-strategy.md)
- [docs/architecture/database/partitioning-strategy.md](docs/architecture/database/partitioning-strategy.md)
- [docs/architecture/database/erd/resource-inventory.mmd](docs/architecture/database/erd/resource-inventory.mmd)
- [docs/development/database.md](docs/development/database.md)

## Prerequisites
- macOS with Apple Silicon
- Colima running with Docker support
- Docker Engine and Docker Compose
- GNU Make

## Directory overview
The repository includes initial directories for application code, background workers, collectors, database assets, Redis support, DefectDojo integration, scripts, backups, configuration, data, logs, documentation, and infrastructure helpers.

## Makefile command overview
The repository provides the following targets:
- `make help` shows the available commands
- `make env` creates `.env` from `.env.example` only when `.env` is missing
- `make config` validates the Docker Compose configuration
- `make build` builds the stack
- `make up` starts the stack in detached mode
- `make status` shows the container status
- `make logs` shows API logs without color
- `make smoke-test` runs the Docker Compose smoke test
- `make db-upgrade` applies Alembic migrations
- `make db-downgrade` downgrades the schema to empty
- `make db-current` shows the current Alembic revision
- `make db-history` shows migration history
- `make db-seed` seeds baseline managed reference catalogs
- `make db-test` runs isolated database tests
- `make down` stops the stack without deleting named volumes
- `make reset` stops the stack and deletes named volumes only after `CONFIRM_RESET=yes`

## First-time setup
1. Copy the example environment file: `cp .env.example .env`
2. Review the local-development defaults in `.env.example` before starting the stack.
3. Run `make help` to review the available workflow commands.

## Normal workflow
- Validate the Compose configuration: `make config`
- Build the images: `make build`
- Start the stack: `make up`
- Check service status: `make status`
- Review API logs: `make logs`
- Stop the stack: `make down`

## Automated smoke test
Run the full smoke test with:
- `make smoke-test`

The smoke test:
- runs from the repository root and also works when invoked from a different working directory via its absolute or relative path;
- validates the Docker daemon and Docker Compose availability;
- creates `.env` only when it is absent and preserves an existing `.env`;
- validates `docker compose config`, builds the stack, starts the services, waits for `api`, `postgres`, and `redis` to become healthy, verifies the expected API JSON values, validates PostgreSQL readiness, checks that Redis returns `PONG`, and then stops the stack while preserving named volumes.

## Timeout overrides
You can override the health-wait timeout and polling interval for the smoke test:
- `SMOKE_TEST_TIMEOUT=180 make smoke-test`
- `SMOKE_TEST_INTERVAL=3 make smoke-test`

## Difference between `make down` and `make reset`
- `make down` stops containers without removing named volumes.
- `make reset` removes PostgreSQL and Redis data volumes only when `CONFIRM_RESET=yes` is provided.

## Reset warning
`make reset` is destructive for named-volume data. Use it only when you intend to delete local PostgreSQL and Redis data.

## Troubleshooting
If health checks fail, inspect the service status and logs with:
- `make status`
- `make logs`
- `docker compose ps -a`
- `docker compose logs --no-color api`
- `docker compose logs --no-color postgres`
- `docker compose logs --no-color redis`

## Service overview
- `api`: FastAPI application on port `8000` with root and health endpoints
- `postgres`: PostgreSQL 16 with a named persistent volume and health checks
- `redis`: Redis 7 with a named persistent volume and health checks

## Deferred functionality
Redis integration beyond basic service startup, workers, collectors, DefectDojo, monitoring, authentication, API persistence endpoints, repositories, and business logic remain deferred beyond this stage.
