.DEFAULT_GOAL := help

ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

.PHONY: help env config build up status logs smoke-test down reset

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

down:
	@cd "$(ROOT_DIR)" && docker compose down

reset:
	@if [ "$(CONFIRM_RESET)" != "yes" ]; then \
		echo 'Reset requires CONFIRM_RESET=yes'; \
		exit 1; \
	fi
	@cd "$(ROOT_DIR)" && docker compose down -v
