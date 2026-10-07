VENV ?= .venv
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
COMPOSE = docker compose --env-file .env -f ops/compose.yaml
BASE_URL ?= http://127.0.0.1:8000

.PHONY: help env install check test syntax contract-check dev down logs compose-check smoke smoke-unready
help:
	@printf '%s\n' 'make env              Create ignored local development configuration' 'make install          Install pinned dependencies into .venv' 'make check            Python/TOML/YAML syntax and backend unit/HTTP tests' 'make dev              Build and start local API + PostgreSQL' 'make smoke            Real HTTP liveness + database readiness' 'make smoke-unready    Real HTTP liveness + failed database readiness' 'make down             Stop containers, preserve database volume'
env:
	$(PYTHON) ops/init_env.py
install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -r backend/requirements-dev.lock
	$(VENV)/bin/python -m pip check
check: syntax test contract-check
syntax:
	$(PYTHON) ops/check_syntax.py
test:
	PYTHONPATH=backend $(PYTHON) -m unittest discover -s backend/tests -p 'test_*.py' -v
contract-check:
	$(PYTHON) ops/check_contract.py
compose-check:
	$(COMPOSE) config --quiet
dev: env compose-check
	$(COMPOSE) up --build --detach --wait --wait-timeout 120
down:
	$(COMPOSE) down
logs:
	$(COMPOSE) logs --tail=100 api db
smoke:
	$(PYTHON) ops/smoke.py --base-url $(BASE_URL)
smoke-unready:
	$(PYTHON) ops/smoke.py --base-url $(BASE_URL) --unready
