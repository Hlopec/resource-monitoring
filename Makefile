.DEFAULT_GOAL := help

ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

.PHONY: help env config build up status logs smoke-test down reset db-upgrade db-downgrade db-current db-history db-seed db-test

help:
	@echo 'Available targets:'
	@echo '  make help           Show this help message'
	@echo '  make env            Create .env from .env.example if it is absent'
	@echo '  make config         Validate the Docker Compose configuration'
	@echo '  make build          Build the Docker Compose services'
	@echo '  make up             Start the Docker Compose services in detached mode'
	@echo '  make status         Show the status of the Docker Compose services'
	@echo '  make logs           Show API logs without color'
	@echo '  make smoke-test     Run the full Docker Compose smoke test'
	@echo '  make db-upgrade     Apply Alembic migrations to the development database'
	@echo '  make db-downgrade   Downgrade the development database to an empty schema'
	@echo '  make db-current     Show the current Alembic revision'
	@echo '  make db-history     Show Alembic migration history'
	@echo '  make db-seed        Seed baseline managed reference catalogs'
	@echo '  make db-test        Run isolated database tests'
	@echo '  make down           Stop the Docker Compose services without deleting volumes'
	@echo '  make reset          Stop the Docker Compose services and delete volumes after confirmation'

env:
	@cd "$(ROOT_DIR)" && if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo 'Created .env from .env.example'; \
	else \
		echo '.env already exists; leaving it unchanged.'; \
	fi

config:
	@cd "$(ROOT_DIR)" && docker compose config

build:
	@cd "$(ROOT_DIR)" && docker compose build

up:
	@cd "$(ROOT_DIR)" && docker compose up -d

status:
	@cd "$(ROOT_DIR)" && docker compose ps

logs:
	@cd "$(ROOT_DIR)" && docker compose logs --no-color api

smoke-test:
	@cd "$(ROOT_DIR)" && ./scripts/docker-smoke-test.sh

db-upgrade:
	@cd "$(ROOT_DIR)" && docker compose up -d postgres
	@cd "$(ROOT_DIR)" && docker compose run --rm --build --no-deps api alembic upgrade head

db-downgrade:
	@cd "$(ROOT_DIR)" && docker compose up -d postgres
	@cd "$(ROOT_DIR)" && docker compose run --rm --build --no-deps api alembic downgrade base

db-current:
	@cd "$(ROOT_DIR)" && docker compose up -d postgres
	@cd "$(ROOT_DIR)" && docker compose run --rm --build --no-deps api alembic current

db-history:
	@cd "$(ROOT_DIR)" && docker compose run --rm --build --no-deps api alembic history

db-seed:
	@cd "$(ROOT_DIR)" && docker compose up -d postgres
	@cd "$(ROOT_DIR)" && docker compose run --rm --build --no-deps api python -m app.db.seed_cli

db-test:
	@cd "$(ROOT_DIR)" && docker compose up -d postgres
	@cd "$(ROOT_DIR)" && docker compose run --rm --build --no-deps -e POSTGRES_DB=resource_monitoring_test api pytest -q

down:
	@cd "$(ROOT_DIR)" && docker compose down

reset:
	@if [ "$(CONFIRM_RESET)" != "yes" ]; then \
		echo 'Reset requires CONFIRM_RESET=yes'; \
		exit 1; \
	fi
	@cd "$(ROOT_DIR)" && docker compose down -v
