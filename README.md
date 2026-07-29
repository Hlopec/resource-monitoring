# resource-monitoring
Platform for automated discovery, monitoring, vulnerability assessment, and security analytics of Internet-facing IT resources.

## Project purpose
This repository is being prepared as a local development workspace for a resource monitoring platform. The initial focus is to establish a clear project structure for future API, worker, collector, database, and integration components.

## Current development stage
The project is currently in stage 01.2: initial project structure. Docker services and Compose-based orchestration are intentionally deferred to stage 01.3.

## Local development assumptions
The local environment is expected to run on macOS with Apple Silicon using Colima and Docker. The project layout is intended to support future Docker Compose-based development workflows.

## Directory structure
The repository currently includes the following top-level areas:

- api/ for application services
- workers/ for background processing components
- collectors/ for data collection logic
- database/ for persistence-related assets
- redis/ for Redis-related assets
- integrations/defectdojo/ for DefectDojo integration code
- infrastructure/docker/ for container-related infrastructure files
- scripts/ for helper scripts
- docs/ for documentation
- tests/ for automated tests

## Notes
Docker services and Compose configuration will be introduced in a later stage; this task only establishes the initial repository structure and supporting placeholders.
